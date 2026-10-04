"""Piezas compartidas por calibrar.py, lora.py y evaluar.py.

Laya calcula, para cada pregunta, un logit por opción y los convierte en probabilidades con
`softmax(logits / T)`. La temperatura T sale del `rl_agent_config.json` del checkpoint, por tipo
de pregunta (`temperature`) o por tipo y número de opciones (`temperature_by_options`, cubetas
como `choice:3-5`). El multilingüe trae todas a 1.0, es decir, sin calibrar.

Aquí se obtienen los logits crudos (antes de dividir por T) para poder medir y ajustar. Se usan
`_check_question`, `_to_internal` y `_encode_state` de `laya.Agent`, que son privados: están
probados con laya==0.3.20, la versión fijada en requirements.txt.
"""
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
DATOS = Path(__file__).resolve().parent / "datos"


# ------------------------------------------------------------------ datos

def leer_jsonl(ruta: Path) -> List[Dict[str, Any]]:
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(linea) for linea in f if linea.strip()]


def indice_respuesta(pregunta: Dict[str, Any], respuesta: Any) -> int:
    """Posición de la respuesta correcta entre las opciones, en el orden en que las ve Laya.

    - choice: el orden de las claves de `criteria`.
    - score: el nivel (0, 1, 2...).
    - noul: Laya pone siempre primero «false» y después «true».
    """
    tipo = pregunta["type"]
    if tipo == "choice":
        claves = list(pregunta["criteria"])
        if respuesta not in claves:
            raise ValueError(f"respuesta {respuesta!r} no está entre las opciones {claves}")
        return claves.index(respuesta)
    if tipo == "score":
        niveles = len(pregunta["criteria"])
        if not isinstance(respuesta, int) or not 0 <= respuesta < niveles:
            raise ValueError(f"nivel {respuesta!r} fuera de 0..{niveles - 1}")
        return respuesta
    if not isinstance(respuesta, bool):
        raise ValueError(f"una pregunta noul se etiqueta con true/false, no con {respuesta!r}")
    return int(respuesta)


def reordenar_opciones(pregunta: Dict[str, Any], orden: Sequence[str]) -> Dict[str, Any]:
    """Copia de una pregunta `choice` con las opciones en otro orden (la etiqueta va por nombre)."""
    criterios = pregunta["criteria"]
    if isinstance(criterios, list):
        return {**pregunta, "criteria": list(orden)}
    return {**pregunta, "criteria": {k: criterios[k] for k in orden}}


def barajar_caso(caso: Dict[str, Any], azar: random.Random) -> Dict[str, Any]:
    """El mismo caso con las opciones de cada `choice` barajadas.

    Solo se barajan las `choice`: en `score` el orden es la escala y en `noul` lo fija Laya.
    Entrenar así ataca el sesgo de orden del artículo (Albacete o Puertollano).
    """
    preguntas = {}
    for qid, q in caso["questions"].items():
        if q["type"] == "choice":
            claves = list(q["criteria"])
            q = reordenar_opciones(q, azar.sample(claves, len(claves)))
        preguntas[qid] = q
    return {**caso, "questions": preguntas}


# ------------------------------------------------------------------ modelo

def ruta_checkpoint(nombre: str = "multilingual") -> str:
    """Carpeta local del checkpoint fijado en app/cerebro.py (lo descarga si no está)."""
    from huggingface_hub import snapshot_download

    from app.cerebro import CHECKPOINTS, REPO, REVISION, _patrones

    ruta = snapshot_download(REPO, revision=REVISION, allow_patterns=_patrones(nombre))
    sub = CHECKPOINTS[nombre]
    return str(Path(ruta) / sub) if sub else ruta


def cargar_agente(modelo: Optional[str] = None, checkpoint: str = "multilingual",
                  dispositivo: str = "cpu"):
    """Un `laya.Agent` en fp32. `modelo` es una carpeta local (p. ej. la que exporta lora.py)."""
    import laya

    agente = laya.Agent(modelo or ruta_checkpoint(checkpoint), device=dispositivo)
    # Todo el entrenamiento y la medida van en fp32: es lo exacto, y en las GTX 16xx (sin tensor
    # cores) además es lo rápido.
    agente.amp_enabled = False
    agente.model.float()
    return agente


def codificar(agente, caso: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Las filas que Laya pasaría al modelo para este caso, una por pregunta etiquetada.

    Cada fila lleva además `target` (reparto de probabilidad correcto, aquí todo en la buena),
    `label`, `qid` y `k` (número de opciones).
    """
    preguntas = caso["questions"]
    ids = [qid for qid in preguntas if qid in caso["respuestas"]]
    for qid in ids:
        agente._check_question(qid, preguntas[qid])
    internas = {qid: agente._to_internal(preguntas[qid]) for qid in ids}
    filas = agente._encode_state(caso["state"], ids, internas)
    for qid, fila in zip(ids, filas):
        k = len(fila["markers"])
        etiqueta = indice_respuesta(preguntas[qid], caso["respuestas"][qid])
        fila.update(qid=qid, k=k, label=etiqueta,
                    target=[1.0 if i == etiqueta else 0.0 for i in range(k)])
    return filas


@dataclass
class Registro:
    """Lo que dijo el modelo para una pregunta, antes de aplicar ninguna temperatura."""
    qid: str
    qtype: int
    k: int
    logits: np.ndarray
    label: int


def logits_crudos(agente, casos: Iterable[Dict[str, Any]], lote: int = 16,
                  avance: Optional[Callable[[int, int], None]] = None) -> List[Registro]:
    """Pasa los casos por el modelo y devuelve los logits sin dividir por la temperatura.

    `avance(hechas, total)` se llama tras cada lote, para ir informando del progreso.
    """
    import torch
    from laya.common import collate_items

    filas = [f for caso in casos for f in codificar(agente, caso)]
    registros: List[Registro] = []
    agente.model.eval()
    with torch.no_grad():
        for i in range(0, len(filas), lote):
            trozo = filas[i:i + lote]
            b = collate_items([trozo], agente.tok.pad_token_id)
            logits, _ = agente.model(*(b[c].to(agente.device) for c in
                                       ("input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype")))
            logits = logits.float().cpu().numpy()
            for j, fila in enumerate(trozo):
                registros.append(Registro(fila["qid"], fila["qtype"], fila["k"],
                                          logits[j, :fila["k"]].copy(), fila["label"]))
            if avance:
                avance(len(registros), len(filas))
    return registros


# ------------------------------------------------------------------ temperaturas

def cubeta(r: Registro) -> str:
    from laya.common import temp_bucket

    return temp_bucket(r.qtype, r.k)


def temperatura_de(r: Registro, calibracion: Optional[Dict[str, Any]]) -> float:
    """La temperatura que aplicaría Laya a este registro con esa calibración (None = 1.0)."""
    if not calibracion:
        return 1.0
    por_opciones = calibracion.get("temperature_by_options", {})
    return float(por_opciones.get(cubeta(r), calibracion.get("temperature", [1.0] * 3)[r.qtype]))


def softmax(z: np.ndarray) -> np.ndarray:
    e = np.exp(z - z.max())
    return e / e.sum()


def nll(registros: Sequence[Registro], t: float) -> float:
    """Pérdida logarítmica media con temperatura t: lo que se minimiza al calibrar."""
    total = 0.0
    for r in registros:
        z = r.logits / t
        total += math.log(np.exp(z - z.max()).sum()) + z.max() - z[r.label]
    return total / max(1, len(registros))


def ajustar_temperatura(registros: Sequence[Registro]) -> float:
    """La T que minimiza la pérdida logarítmica, buscada entre los límites que acepta Laya."""
    from laya.common import TEMP_MAX, TEMP_MIN

    rejilla = np.exp(np.linspace(math.log(TEMP_MIN), math.log(TEMP_MAX), 241))
    return float(min(rejilla, key=lambda t: nll(registros, t)))


def calibrar(registros: Sequence[Registro], minimo_cubeta: int = 30) -> Dict[str, Any]:
    """Una temperatura por tipo de pregunta y, si hay datos de sobra, otra por cubeta.

    Las cubetas con menos de `minimo_cubeta` respuestas no se ajustan por separado: heredan la
    del tipo, que se ajusta con todas las de ese tipo.
    """
    from laya.common import QTYPE_NAMES

    temperaturas = [1.0, 1.0, 1.0]
    for tipo in range(3):
        del_tipo = [r for r in registros if r.qtype == tipo]
        if del_tipo:
            temperaturas[tipo] = round(ajustar_temperatura(del_tipo), 4)

    por_opciones: Dict[str, float] = {}
    cubetas: Dict[str, List[Registro]] = {}
    for r in registros:
        cubetas.setdefault(cubeta(r), []).append(r)
    for nombre, grupo in sorted(cubetas.items()):
        if len(grupo) >= minimo_cubeta:
            por_opciones[nombre] = round(ajustar_temperatura(grupo), 4)

    return {
        "temperature": temperaturas,
        "temperature_by_options": por_opciones,
        "respuestas_por_cubeta": {n: len(g) for n, g in sorted(cubetas.items())},
        "tipos": list(QTYPE_NAMES),
    }


# ------------------------------------------------------------------ métricas

def metricas(registros: Sequence[Registro], calibracion: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Aciertos, ECE y pérdida logarítmica, en total y por pregunta.

    ECE (error de calibración esperado): se agrupan las respuestas por la seguridad declarada
    (max p) y se compara con la proporción de aciertos de cada grupo. 0 es perfecto.
    """
    from laya.common import ece_score

    def resumen(grupo: Sequence[Registro]) -> Dict[str, Any]:
        probs = [softmax(r.logits / temperatura_de(r, calibracion)) for r in grupo]
        conf = np.array([p.max() for p in probs])
        bien = np.array([int(p.argmax()) == r.label for p, r in zip(probs, grupo)], dtype=float)
        perdida = float(np.mean([-math.log(max(p[r.label], 1e-12)) for p, r in zip(probs, grupo)]))
        return {"n": len(grupo), "aciertos": round(float(bien.mean()), 4),
                "seguridad_media": round(float(conf.mean()), 4),
                "ece": round(float(ece_score(conf, bien)), 4), "nll": round(perdida, 4)}

    por_pregunta: Dict[str, List[Registro]] = {}
    for r in registros:
        por_pregunta.setdefault(r.qid, []).append(r)
    return {"total": resumen(registros),
            "por_pregunta": {q: resumen(g) for q, g in sorted(por_pregunta.items())}}


def tabla(titulo: str, m: Dict[str, Any]) -> str:
    filas = [("TOTAL", m["total"])] + list(m["por_pregunta"].items())
    lineas = [titulo, f"  {'pregunta':<14}{'n':>5}{'aciertos':>10}{'seguridad':>11}{'ECE':>8}{'NLL':>8}"]
    for nombre, r in filas:
        lineas.append(f"  {nombre:<14}{r['n']:>5}{r['aciertos']:>10.1%}{r['seguridad_media']:>11.1%}"
                      f"{r['ece']:>8.3f}{r['nll']:>8.3f}")
    return "\n".join(lineas)


def guardar_json(ruta: Path, datos: Dict[str, Any]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")
