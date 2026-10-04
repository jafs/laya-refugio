"""Mide un modelo (con o sin calibración) con las situaciones de prueba y las del artículo.

Además de aciertos y ECE, repite cada pregunta `choice` con las opciones en orden inverso y
cuenta cuántas veces cambia la respuesta: el sesgo de orden del artículo.

Uso:
    python -m entrenamiento.evaluar                                        # el original
    python -m entrenamiento.evaluar --calibracion calibracion/multilingual.json
    python -m entrenamiento.evaluar --modelo modelos/lora-refugio --calibracion calibracion/lora-refugio.json

Va bien en CPU (un par de minutos); --dispositivo cuda para ir más rápido.
"""
import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import comun
from .progreso import Progreso


def invertir_choices(caso: Dict[str, Any]) -> Dict[str, Any]:
    preguntas = {qid: comun.reordenar_opciones(q, list(reversed(list(q["criteria"]))))
                 if q["type"] == "choice" else q for qid, q in caso["questions"].items()}
    return {**caso, "questions": preguntas}


def eleccion(r: comun.Registro, caso: Dict[str, Any]) -> str:
    return list(caso["questions"][r.qid]["criteria"])[int(r.logits.argmax())]


def opciones_de(pregunta: Dict[str, Any]) -> List[str]:
    if pregunta["type"] == "choice":
        return list(pregunta["criteria"])
    if pregunta["type"] == "score":
        return [str(i) for i in range(len(pregunta["criteria"]))]
    return ["false", "true"]


def sesgo_de_orden(agente, casos: List[Dict[str, Any]],
                   avance: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """Proporción de respuestas `choice` que cambian al invertir el orden de las opciones."""
    solo_choice = [{**c, "respuestas": {q: v for q, v in c["respuestas"].items()
                                        if c["questions"][q]["type"] == "choice"}} for c in casos]
    solo_choice = [c for c in solo_choice if c["respuestas"]]
    invertidos = [invertir_choices(c) for c in solo_choice]
    directo = comun.logits_crudos(agente, solo_choice)
    inverso = comun.logits_crudos(agente, invertidos, avance=avance)
    # Cada caso aporta sus filas en el mismo orden en las dos pasadas.
    casos_por_fila = [c for c in solo_choice for _ in c["respuestas"]]
    casos_inv_por_fila = [c for c in invertidos for _ in c["respuestas"]]
    cambios = sum(eleccion(a, c) != eleccion(b, ci)
                  for a, b, c, ci in zip(directo, inverso, casos_por_fila, casos_inv_por_fila))
    return {"preguntas": len(directo), "cambian": cambios,
            "proporcion": round(cambios / max(1, len(directo)), 4)}


def casos_articulo(agente, casos: List[Dict[str, Any]], calibracion: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    filas = []
    for caso in casos:
        for r in comun.logits_crudos(agente, [caso]):
            p = comun.softmax(r.logits / comun.temperatura_de(r, calibracion))
            opciones = opciones_de(caso["questions"][r.qid])
            dicho = opciones[int(p.argmax())]
            filas.append({"variante": caso.get("variante", ""), "pregunta": r.qid, "dice": dicho,
                          "esperado": opciones[r.label], "seguridad": round(float(p.max()), 4),
                          "ok": dicho == opciones[r.label]})
    return filas


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--modelo", help="carpeta de un checkpoint local; por defecto, el de Hugging Face")
    p.add_argument("--checkpoint", default="multilingual", choices=["multilingual", "english"])
    p.add_argument("--calibracion", type=Path, help="JSON que escribe calibrar.py")
    p.add_argument("--dispositivo", default="cpu")
    p.add_argument("--prueba", type=Path, default=comun.DATOS / "prueba.jsonl")
    p.add_argument("--articulo", type=Path, default=comun.DATOS / "articulo.jsonl")
    p.add_argument("--progreso", type=Path, help="fichero JSONL de eventos para la terminal web")
    a = p.parse_args()
    progreso = Progreso(a.progreso)

    calibracion = None
    if a.calibracion:
        with open(a.calibracion, encoding="utf-8") as f:
            calibracion = json.load(f)

    t0 = time.time()
    nombre = Path(a.modelo).name if a.modelo else a.checkpoint
    progreso("inicio", script="evaluar", modelo=nombre, calibrado=bool(calibracion))
    progreso("fase", texto="cargando el modelo")
    agente = comun.cargar_agente(a.modelo, a.checkpoint, a.dispositivo)
    print(f"Modelo: {a.modelo or a.checkpoint} | calibración: {a.calibracion or 'ninguna (T = 1)'} | {agente.device}\n")
    progreso("fase", texto=f"modelo cargado en {agente.device}", dispositivo=str(agente.device))

    prueba = comun.leer_jsonl(a.prueba)
    metricas = comun.metricas(comun.logits_crudos(agente, prueba, avance=progreso.avance("situaciones de prueba")),
                              calibracion)
    print(comun.tabla(f"Prueba ({a.prueba.name}, frases que no se usan al entrenar)", metricas))

    articulo = casos_articulo(agente, comun.leer_jsonl(a.articulo), calibracion)
    print(f"\nEjemplos del artículo ({a.articulo.name}):")
    for f in articulo:
        print(f"  {'ok ' if f['ok'] else 'MAL'} {f['variante']:<22}{f['pregunta']:<14}{f['dice']:<12}"
              f"{f['seguridad']:>6.0%}" + ("" if f["ok"] else f"   (esperado: {f['esperado']})"))

    orden = sesgo_de_orden(agente, prueba, avance=progreso.avance("opciones en orden inverso"))
    print(f"\nSesgo de orden: al invertir las opciones cambia la respuesta en {orden['cambian']} de "
          f"{orden['preguntas']} preguntas choice ({orden['proporcion']:.1%}). La calibración no lo arregla.")
    print(f"\n({time.time() - t0:.0f} s)")
    progreso("resultado", metricas=metricas, articulo=articulo, orden=orden)
    progreso("fin", segundos=round(time.time() - t0))


if __name__ == "__main__":
    main()
