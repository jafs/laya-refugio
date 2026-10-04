"""Entrenamientos lanzados desde la terminal: calibrar, entrenar una LoRA y evaluar.

Cada trabajo es un proceso aparte (`python -m entrenamiento.<script> --progreso ...`), así que un
entrenamiento que falla o se queda sin memoria no tira el servidor. El servidor solo lee el
fichero de eventos que va escribiendo el script y lo resume para la web. Solo hay un trabajo a
la vez: la GPU no da para más.

Cada trabajo deja su carpeta en `entrenos/` (orden.json, progreso.jsonl y salida.log), que git
ignora.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

RAIZ = Path(__file__).resolve().parent.parent
NOMBRE_VALIDO = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
ORIGINAL = "original"
# Puntos de la curva de pérdida que se mandan a la web, como mucho.
PUNTOS_CURVA = 160


class Orden(BaseModel):
    tipo: Literal["calibrar", "lora", "evaluar"]
    dispositivo: Literal["auto", "cpu", "cuda"] = "auto"
    # calibrar y evaluar: qué cerebro. lora: cómo se llamará el nuevo.
    modelo: str = ORIGINAL
    calibrado: bool = True                          # evaluar
    epocas: int = Field(default=3, ge=1, le=10)     # lora
    rango: Literal[4, 8, 16, 32] = 8
    max_casos: Optional[int] = Field(default=None, ge=10, le=100_000)
    barajar: bool = True


# ------------------------------------------------------------------ cerebros

def cerebros_disponibles(raiz: Path = RAIZ) -> List[Dict[str, Any]]:
    """El modelo original y cada checkpoint de modelos/, con su calibración si la tienen."""
    def calibracion(nombre: str) -> Optional[str]:
        ruta = raiz / "calibracion" / f"{nombre}.json"
        return ruta.relative_to(raiz).as_posix() if ruta.is_file() else None

    cerebros = [{"id": ORIGINAL, "modelo": None, "calibracion": calibracion("multilingual"),
                 "descripcion": "Laya multilingüe tal como se descarga"}]
    carpeta = raiz / "modelos"
    for d in sorted(carpeta.iterdir()) if carpeta.is_dir() else []:
        if not (d / "rl_agent_config.json").is_file() or not NOMBRE_VALIDO.match(d.name):
            continue
        info = {}
        if (d / "lora.json").is_file():
            info = json.loads((d / "lora.json").read_text(encoding="utf-8"))
        historial = info.get("historial") or [{}]
        descripcion = (f"LoRA r={info.get('rango')} · {info.get('epocas')} épocas · {info.get('casos')} casos"
                       f" · validación {historial[-1].get('aciertos', 0):.1%}") if info else "checkpoint local"
        cerebros.append({"id": d.name, "modelo": d.relative_to(raiz).as_posix(),
                         "calibracion": calibracion(d.name), "descripcion": descripcion,
                         "fecha": info.get("fecha")})
    return cerebros


def buscar_cerebro(nombre: str, raiz: Path = RAIZ) -> Dict[str, Any]:
    for c in cerebros_disponibles(raiz):
        if c["id"] == nombre:
            return c
    raise ValueError(f"No hay ningún cerebro llamado {nombre!r}")


# ------------------------------------------------------------------ resumen de eventos

def leer_eventos(ruta: Path) -> List[Dict[str, Any]]:
    if not ruta.is_file():
        return []
    eventos = []
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            try:
                eventos.append(json.loads(linea))
            except json.JSONDecodeError:
                pass        # la última línea puede estar a medio escribir
    return eventos


def resumir(eventos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Lo que la web necesita para pintar el progreso, sin mandarle cada evento."""
    r: Dict[str, Any] = {"fase": None, "avance": None, "lote": None, "epocas": [], "curva": [],
                         "modelo": None, "validacion_inicial": None, "resultado": None, "fin": None}
    perdidas = []
    for e in eventos:
        tipo = e.get("tipo")
        if tipo == "inicio":
            r["inicio"] = e
        elif tipo == "fase":
            r["fase"] = e.get("texto")
            r["avance"] = None
        elif tipo == "avance":
            r["avance"] = {k: e.get(k) for k in ("etapa", "hechas", "total")}
        elif tipo == "modelo":
            r["modelo"] = e
        elif tipo == "validacion_inicial":
            r["validacion_inicial"] = e
        elif tipo == "lote":
            r["lote"] = e
            perdidas.append(e.get("perdida"))
        elif tipo == "epoca":
            r["epocas"].append(e)
        elif tipo == "resultado":
            r["resultado"] = e
        elif tipo == "fin":
            r["fin"] = e
    # La curva se resume en tramos, con la media de cada uno, para que no pese.
    if perdidas:
        tramo = max(1, -(-len(perdidas) // PUNTOS_CURVA))
        r["curva"] = [round(sum(perdidas[i:i + tramo]) / len(perdidas[i:i + tramo]), 4)
                      for i in range(0, len(perdidas), tramo)]
    return r


def cola(ruta: Path, lineas: int = 25) -> str:
    if not ruta.is_file():
        return ""
    texto = ruta.read_text(encoding="utf-8", errors="replace").replace("\r", "\n")
    utiles = [l for l in texto.splitlines() if l.strip() and "Warning" not in l]
    return "\n".join(utiles[-lineas:])


# ------------------------------------------------------------------ gestor

class Entrenos:
    def __init__(self, raiz: Path = RAIZ, python: str = sys.executable):
        self.raiz = raiz
        self.python = python
        self.carpeta = raiz / "entrenos"
        self._lock = threading.Lock()
        self._proceso: Optional[subprocess.Popen] = None
        self._actual: Optional[Path] = None
        self._cancelado = False

    def comando(self, orden: Orden, progreso: Path) -> List[str]:
        base = [self.python, "-m", f"entrenamiento.{orden.tipo}", "--progreso", str(progreso)]
        dispositivo = orden.dispositivo
        if orden.tipo == "lora":
            if not NOMBRE_VALIDO.match(orden.modelo) or orden.modelo == ORIGINAL:
                raise ValueError("El nombre de la LoRA solo admite minúsculas, números y guiones "
                                 f"(y no puede ser «{ORIGINAL}»)")
            base += ["--nombre", orden.modelo, "--epocas", str(orden.epocas), "--rango", str(orden.rango),
                     "--dispositivo", dispositivo]
            if orden.max_casos:
                base += ["--max-casos", str(orden.max_casos)]
            if not orden.barajar:
                base.append("--sin-barajar")
            return base

        cerebro = buscar_cerebro(orden.modelo, self.raiz)
        if dispositivo == "auto":
            # Sin gradientes, la CPU basta; con GPU, mejor si hay.
            dispositivo = "cuda" if _hay_cuda() else "cpu"
        base += ["--dispositivo", dispositivo]
        if cerebro["modelo"]:
            base += ["--modelo", cerebro["modelo"]]
        if orden.tipo == "evaluar" and orden.calibrado:
            if not cerebro["calibracion"]:
                raise ValueError(f"{orden.modelo} no tiene calibración todavía: calíbralo antes o evalúalo sin ella")
            base += ["--calibracion", cerebro["calibracion"]]
        return base

    def lanzar(self, orden: Orden) -> Dict[str, Any]:
        with self._lock:
            if self._proceso and self._proceso.poll() is None:
                raise RuntimeError("Ya hay un trabajo en marcha: espera a que termine o cancélalo")
            carpeta = self.carpeta / f"{time.strftime('%Y%m%d-%H%M%S')}-{orden.tipo}"
            progreso = carpeta / "progreso.jsonl"
            comando = self.comando(orden, progreso)     # valida la orden antes de crear nada
            carpeta.mkdir(parents=True, exist_ok=True)
            (carpeta / "orden.json").write_text(json.dumps(
                {"orden": orden.model_dump(), "comando": comando, "lanzado": time.time()},
                ensure_ascii=False, indent=2), encoding="utf-8")
            entorno = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
            salida = open(carpeta / "salida.log", "w", encoding="utf-8")
            extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            self._proceso = subprocess.Popen(comando, cwd=self.raiz, stdout=salida, stderr=subprocess.STDOUT,
                                             env=entorno, **extra)
            salida.close()
            self._actual = carpeta
            self._cancelado = False
        return self.estado()

    def cancelar(self) -> Dict[str, Any]:
        with self._lock:
            if self._proceso and self._proceso.poll() is None:
                self._cancelado = True
                self._proceso.terminate()
                try:
                    self._proceso.wait(10)
                except subprocess.TimeoutExpired:
                    self._proceso.kill()
        return self.estado()

    def _ultimo(self) -> Optional[Path]:
        if self._actual:
            return self._actual
        if not self.carpeta.is_dir():
            return None
        trabajos = sorted(d for d in self.carpeta.iterdir() if (d / "orden.json").is_file())
        return trabajos[-1] if trabajos else None

    def estado(self) -> Dict[str, Any]:
        carpeta = self._ultimo()
        if carpeta is None:
            return {"estado": "nada"}
        orden = json.loads((carpeta / "orden.json").read_text(encoding="utf-8"))
        resumen = resumir(leer_eventos(carpeta / "progreso.jsonl"))
        if carpeta == self._actual and self._proceso is not None:
            codigo = self._proceso.poll()
            if codigo is None:
                estado = "en_curso"
            elif self._cancelado:
                estado = "cancelado"
            else:
                estado = "terminado" if codigo == 0 and resumen["fin"] else "error"
        else:
            # Un trabajo de otra sesión del servidor: solo sabemos lo que dejó escrito.
            estado = "terminado" if resumen["fin"] else "interrumpido"
        return {"estado": estado, "id": carpeta.name, "orden": orden["orden"],
                "lanzado": orden.get("lanzado"), "registro": cola(carpeta / "salida.log"), **resumen}

    @property
    def en_curso(self) -> bool:
        return bool(self._proceso and self._proceso.poll() is None)


def _hay_cuda() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:  # noqa: BLE001
        return False
