"""El cerebro del refugio: descarga Laya una sola vez, lo carga en segundo plano y responde.

La primera ejecución descarga los checkpoints a la caché de Hugging Face. Las siguientes los
buscan primero en local (`local_files_only`), así que arrancan sin tocar la red. La revisión
del modelo está fijada en REVISION: si la caché solo tiene otra, se descarga la buena.
"""
import os
import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = "convaiinnovations/laya"
# Versión fija de los pesos: la que se probó con laya==0.3.20. Al subirla se descarga la nueva.
REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
# Subcarpeta de cada checkpoint dentro del repo (el inglés vive en la raíz).
CHECKPOINTS = {"english": None, "multilingual": "multilingual"}
# Tamaño aproximado de la descarga, solo para pintar la barra de progreso.
TAMANO_MB = {"english": 808, "multilingual": 647}
FICHEROS = ("rl_agent_config.json", "model.safetensors", "tokenizer/*", "encoder/*")


def _patrones(nombre: str) -> List[str]:
    sub = CHECKPOINTS[nombre]
    prefijo = f"{sub}/" if sub else ""
    return [prefijo + f for f in FICHEROS]


def _completo(ruta: str, nombre: str) -> bool:
    """¿Están en disco los ficheros imprescindibles del checkpoint?"""
    base = Path(ruta) / (CHECKPOINTS[nombre] or "")
    return (base / "rl_agent_config.json").is_file() and (base / "model.safetensors").is_file()


def _tamano_descarga_mb(patrones: List[str]) -> Optional[int]:
    """Tamaño real de lo que se va a descargar, preguntado a Hugging Face. None si falla."""
    from fnmatch import fnmatch

    from huggingface_hub import HfApi

    try:
        info = HfApi().model_info(REPO, revision=REVISION, files_metadata=True)
    except Exception:  # noqa: BLE001 - la barra de progreso tira de la estimación
        return None
    total = sum(f.size or 0 for f in info.siblings if any(fnmatch(f.rfilename, p) for p in patrones))
    return round(total / 1_048_576) or None


def _tamano_dir(ruta: Path) -> int:
    total = 0
    for raiz, _, ficheros in os.walk(ruta):
        for f in ficheros:
            try:
                total += os.path.getsize(os.path.join(raiz, f))
            except OSError:
                pass
    return total


class Cerebro:
    """Carga los checkpoints pedidos y los sirve a través del `Router` de Laya."""

    def __init__(self, checkpoints: List[str], defecto: str = "multilingual",
                 dispositivo: str = "auto", precision: str = "auto"):
        desconocidos = [c for c in checkpoints if c not in CHECKPOINTS]
        if desconocidos:
            raise ValueError(f"Checkpoints desconocidos: {desconocidos}. Opciones: {sorted(CHECKPOINTS)}")
        if defecto not in checkpoints:
            raise ValueError(f"El checkpoint por defecto ({defecto}) tiene que estar en {checkpoints}")
        self.checkpoints = checkpoints
        self.defecto = defecto
        self.dispositivo_pedido = dispositivo
        if precision not in ("auto", "fp16", "fp32"):
            raise ValueError(f"Precisión desconocida: {precision}. Opciones: auto, fp16, fp32")
        self.precision_pedida = precision
        self.router = None
        self.dispositivo: Optional[str] = None
        self.precision: Optional[str] = None
        self._estado: Dict[str, Any] = {
            "fase": "arrancando",   # arrancando | comprobando | descargando | cargando | listo | error
            "checkpoint": None,
            "descargado_mb": 0,
            "total_mb": 0,
            "descargados": [],      # checkpoints que ha habido que bajar de internet en este arranque
            "error": None,
            "segundos_carga": None,
        }

    # ------------------------------------------------------------------ carga
    def arrancar(self) -> None:
        threading.Thread(target=self._cargar, daemon=True, name="cerebro").start()

    def _cargar(self) -> None:
        t0 = time.time()
        try:
            rutas = {nombre: self._localizar(nombre) for nombre in self.checkpoints}
            self._estado.update(fase="cargando", checkpoint=None)
            self._construir_router(rutas)
            self._estado.update(fase="listo", segundos_carga=round(time.time() - t0, 1))
        except Exception as exc:  # noqa: BLE001 - se enseña tal cual en la terminal
            self._estado.update(fase="error", error=f"{type(exc).__name__}: {exc}")

    def _localizar(self, nombre: str) -> str:
        """Ruta local del checkpoint. Solo descarga si no está ya en la caché."""
        from huggingface_hub import snapshot_download

        patrones = _patrones(nombre)
        self._estado.update(fase="comprobando", checkpoint=nombre)
        try:
            ruta = snapshot_download(REPO, revision=REVISION, allow_patterns=patrones, local_files_only=True)
            if _completo(ruta, nombre):
                return ruta
        except Exception:  # noqa: BLE001 - no está en la caché: toca descargar
            pass

        self._estado.update(fase="descargando", descargado_mb=0,
                            total_mb=_tamano_descarga_mb(patrones) or TAMANO_MB[nombre])
        vigilante = threading.Event()
        threading.Thread(target=self._vigilar_descarga, args=(vigilante,), daemon=True).start()
        try:
            ruta = snapshot_download(REPO, revision=REVISION, allow_patterns=patrones)
        finally:
            vigilante.set()
        self._estado["descargados"].append(nombre)
        return ruta

    def _vigilar_descarga(self, fin: threading.Event) -> None:
        """Mide cuánto crece la caché del repo para dar una idea del progreso."""
        from huggingface_hub import constants

        carpeta = Path(constants.HF_HUB_CACHE) / ("models--" + REPO.replace("/", "--"))
        inicial = _tamano_dir(carpeta) if carpeta.exists() else 0
        while not fin.wait(0.5):
            actual = _tamano_dir(carpeta) if carpeta.exists() else 0
            self._estado["descargado_mb"] = max(0, round((actual - inicial) / 1_048_576))

    def _construir_router(self, rutas: Dict[str, str]) -> None:
        import torch
        from laya import Router

        dispositivo = None if self.dispositivo_pedido == "auto" else self.dispositivo_pedido
        if dispositivo and dispositivo.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(
                f"Se pidió LAYA_DEVICE={dispositivo}, pero esta instalación de torch "
                f"({torch.__version__}) no ve ninguna GPU CUDA."
            )
        modelos = {nombre: (ruta, CHECKPOINTS[nombre]) for nombre, ruta in rutas.items()}
        router = Router(models=modelos, device=dispositivo, default=self.defecto,
                        max_loaded=len(modelos))
        router.preload(list(modelos))   # solo los nuestros; el Router conoce también typed-decisions
        for nombre in modelos:
            agente = router.load(nombre)
            self._ajustar_precision(agente)
            # La primera inferencia paga la inicialización de CUDA/kernels; mejor aquí que en la
            # primera petición de la terminal.
            agente.predict("calentando motores", {"ok": {"type": "noul", "instructions": "¿Listo?"}})
        agente = router.load(self.defecto)
        self.dispositivo = str(agente.device)
        self.precision = "fp32" if not agente.amp_enabled else str(agente.dtype).replace("torch.float", "fp")
        self.router = router

    def _ajustar_precision(self, agente) -> None:
        """Laya usa fp16 en cualquier GPU CUDA, pero en las GTX 16xx (sin tensor cores) el fp16
        es varias veces más lento que el fp32. En modo `auto` se detectan y se pasan a fp32."""
        import torch

        if agente.device.type != "cuda":
            return
        pedida = self.precision_pedida
        if pedida == "auto":
            nombre_gpu = torch.cuda.get_device_name(agente.device)
            pedida = "fp32" if "GTX 16" in nombre_gpu else "fp16"
        if pedida == "fp32":
            agente.amp_enabled = False
            agente.dtype = torch.float32

    # ------------------------------------------------------------------ estado
    @property
    def listo(self) -> bool:
        return self.router is not None

    def estado(self) -> Dict[str, Any]:
        return {
            **self._estado,
            "repo": REPO,
            "checkpoints": self.checkpoints,
            "defecto": self.defecto,
            "dispositivo": self.dispositivo,
            "precision": self.precision,
            "listo": self.listo,
        }

    # ------------------------------------------------------------------ inferencia
    def _modelo_para(self, estado: Any, preguntas: Dict[str, Any], modelo: Optional[str]) -> Dict[str, Any]:
        """Decide el checkpoint. Si el Router elige uno que no hemos descargado, usa el defecto."""
        decision = dict(self.router.route(estado, preguntas, model=modelo))
        if decision["model"] not in self.checkpoints:
            decision["reason"] += f" (no descargado: se usa {self.defecto})"
            decision["model"] = self.defecto
        return decision

    def predecir(self, estado: Any, preguntas: Dict[str, Any], modelo: Optional[str] = None) -> Dict[str, Any]:
        decision = self._modelo_para(estado, preguntas, modelo)
        t0 = time.perf_counter()
        resultado = self.router.predict(estado, preguntas, model=decision["model"])
        resultado["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        resultado["routing"] = {**resultado.get("routing", {}), "model": decision["model"],
                                "reason": decision["reason"]}
        return resultado

    def horda(self, estados: List[Any], preguntas: Dict[str, Any], modelo: Optional[str] = None,
              comparar: bool = True) -> Dict[str, Any]:
        """Evalúa muchos estados con las mismas preguntas en pasadas compartidas."""
        peticiones = []
        for e in estados:
            decision = self._modelo_para(e, preguntas, modelo)
            peticiones.append({"state": e, "questions": preguntas, "model": decision["model"]})

        t0 = time.perf_counter()
        resultados = self.router.predict_batch(peticiones)
        ms_lote = (time.perf_counter() - t0) * 1000

        respuesta = {
            "resultados": resultados,
            "lote_ms": round(ms_lote, 1),
            "lote_ms_por_estado": round(ms_lote / max(1, len(estados)), 1),
        }
        if comparar:
            t0 = time.perf_counter()
            for p in peticiones:
                self.router.predict(p["state"], preguntas, model=p["model"])
            ms_uno = (time.perf_counter() - t0) * 1000
            respuesta.update(uno_a_uno_ms=round(ms_uno, 1),
                             uno_a_uno_ms_por_estado=round(ms_uno / max(1, len(estados)), 1))
        return respuesta

    def barajar(self, estado: Any, preguntas: Dict[str, Any], id_pregunta: str, rondas: int = 6,
                modelo: Optional[str] = None, semilla: Optional[int] = None) -> Dict[str, Any]:
        """Repite una pregunta `choice` con las opciones en distinto orden y compara respuestas.

        Es el experimento de la letra pequeña: si el modelo fuese insensible al orden, todas las
        rondas elegirían lo mismo.
        """
        return barajar(lambda e, q: self.predecir(e, q, modelo), estado, preguntas,
                       id_pregunta, rondas, semilla)


def ordenes_barajados(claves: List[str], rondas: int, azar: random.Random) -> List[List[str]]:
    """El orden original, el invertido y órdenes aleatorios distintos hasta completar `rondas`."""
    ordenes = [list(claves)]
    if len(claves) > 1:
        ordenes.append(list(reversed(claves)))
    intentos = 0
    while len(ordenes) < rondas and intentos < rondas * 20:
        intentos += 1
        candidato = azar.sample(claves, len(claves))
        if candidato not in ordenes:
            ordenes.append(candidato)
    return ordenes[:max(1, rondas)]


def barajar(predecir, estado: Any, preguntas: Dict[str, Any], id_pregunta: str,
            rondas: int = 6, semilla: Optional[int] = None) -> Dict[str, Any]:
    pregunta = preguntas.get(id_pregunta)
    if not pregunta or pregunta.get("type") != "choice":
        raise ValueError(f"'{id_pregunta}' tiene que ser una pregunta de tipo choice")
    criterios = pregunta.get("criteria")
    if isinstance(criterios, list):
        criterios = {c: None for c in criterios}
    if not isinstance(criterios, dict) or len(criterios) < 2:
        raise ValueError("Para barajar hacen falta al menos dos opciones")

    azar = random.Random(semilla)
    resultados = []
    for orden in ordenes_barajados(list(criterios), rondas, azar):
        variante = {**pregunta, "criteria": {k: criterios[k] for k in orden}}
        respuesta = predecir(estado, {id_pregunta: variante})["answers"][id_pregunta]
        resultados.append({
            "orden": orden,
            "eleccion": respuesta["choice"],
            "probabilidad": respuesta["probabilities"][respuesta["choice"]],
        })

    elecciones = [r["eleccion"] for r in resultados]
    return {
        "pregunta": id_pregunta,
        "resultados": resultados,
        "elecciones_distintas": sorted(set(elecciones)),
        "estable": len(set(elecciones)) == 1,
        "cambios": sum(1 for e in elecciones if e != elecciones[0]),
    }
