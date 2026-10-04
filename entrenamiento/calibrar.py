"""Calibra las probabilidades de Laya: ajusta temperaturas sin tocar ni un peso del modelo.

Pasa las situaciones de calibración por el modelo, busca la temperatura que mejor reparte la
seguridad (la que minimiza la pérdida logarítmica) y lo comprueba con las de prueba. Las dos usan
frases que la LoRA no ha visto al entrenar, pero son situaciones distintas. Las respuestas
elegidas no cambian: solo cambia cuánto presume de ellas.

Va bien en CPU: son unos cientos de pasadas sin gradientes.

Uso:
    python -m entrenamiento.calibrar                                  # el multilingüe tal cual
    python -m entrenamiento.calibrar --modelo modelos/lora-refugio    # el que exporta lora.py
    python -m entrenamiento.calibrar --dispositivo cuda               # si quieres ir más rápido

El resultado se guarda en calibracion/<nombre>.json. Para que lo use la terminal:
    LAYA_CALIBRACION=calibracion/multilingual.json ./run.sh
"""
import argparse
import time
from datetime import date
from pathlib import Path

from . import comun
from .progreso import Progreso


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--modelo", help="carpeta de un checkpoint local; por defecto, el de Hugging Face")
    p.add_argument("--checkpoint", default="multilingual", choices=["multilingual", "english"])
    p.add_argument("--dispositivo", default="cpu", help="cpu (por defecto), cuda, cuda:1...")
    p.add_argument("--datos", type=Path, default=comun.DATOS / "calibracion.jsonl")
    p.add_argument("--prueba", type=Path, default=comun.DATOS / "prueba.jsonl")
    p.add_argument("--minimo-cubeta", type=int, default=30,
                   help="respuestas mínimas para ajustar una cubeta (tipo + nº de opciones) por separado")
    p.add_argument("--salida", type=Path, help="por defecto calibracion/<checkpoint o carpeta>.json")
    p.add_argument("--progreso", type=Path, help="fichero JSONL de eventos para la terminal web")
    a = p.parse_args()
    progreso = Progreso(a.progreso)

    nombre = Path(a.modelo).name if a.modelo else a.checkpoint
    salida = a.salida or comun.RAIZ / "calibracion" / f"{nombre}.json"

    t0 = time.time()
    progreso("inicio", script="calibrar", modelo=nombre)
    progreso("fase", texto="cargando el modelo")
    agente = comun.cargar_agente(a.modelo, a.checkpoint, a.dispositivo)
    print(f"Modelo cargado en {agente.device} ({time.time() - t0:.0f} s)")
    progreso("fase", texto=f"modelo cargado en {agente.device}", dispositivo=str(agente.device))

    t0 = time.time()
    calibracion_reg = comun.logits_crudos(agente, comun.leer_jsonl(a.datos),
                                          avance=progreso.avance("situaciones de calibración"))
    prueba_reg = comun.logits_crudos(agente, comun.leer_jsonl(a.prueba),
                                     avance=progreso.avance("situaciones de prueba"))
    print(f"{len(calibracion_reg) + len(prueba_reg)} respuestas en {time.time() - t0:.0f} s\n")

    ajuste = comun.calibrar(calibracion_reg, a.minimo_cubeta)
    antes = comun.metricas(prueba_reg)
    despues = comun.metricas(prueba_reg, ajuste)
    print(comun.tabla(f"Prueba SIN calibrar ({a.prueba.name})", antes))
    print()
    print(comun.tabla(f"Prueba CALIBRADA ({a.prueba.name})", despues))
    print()
    print("Temperaturas por tipo (choice, score, noul):", ajuste["temperature"])
    print("Temperaturas por cubeta:", ajuste["temperature_by_options"] or "ninguna (pocos datos)")
    print("\nLos aciertos no cambian al calibrar; lo que debe bajar es el ECE (y la NLL).")

    comun.guardar_json(salida, {
        "checkpoint": a.checkpoint,
        "modelo": a.modelo,
        "fecha": date.today().isoformat(),
        "datos": str(a.datos.relative_to(comun.RAIZ)) if a.datos.is_relative_to(comun.RAIZ) else str(a.datos),
        "temperature": ajuste["temperature"],
        "temperature_by_options": ajuste["temperature_by_options"],
        "respuestas_por_cubeta": ajuste["respuestas_por_cubeta"],
        "prueba": {"sin_calibrar": antes["total"], "calibrada": despues["total"]},
    })
    relativa = salida.relative_to(comun.RAIZ) if salida.is_relative_to(comun.RAIZ) else salida
    print(f"\nGuardado en {relativa}")
    progreso("resultado", antes=antes, despues=despues, temperaturas=ajuste["temperature"],
             por_cubeta=ajuste["temperature_by_options"], salida=relativa.as_posix())
    progreso("fin", segundos=round(time.time() - t0))


if __name__ == "__main__":
    main()
