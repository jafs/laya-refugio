"""Eventos de progreso para que la terminal web pueda seguir un entrenamiento.

Con `--progreso fichero.jsonl`, los scripts escriben ahí una línea JSON por evento (inicio,
lotes, épocas, resultado, fin). El servidor lanza el script en un proceso aparte y solo lee ese
fichero, así que un entrenamiento que falla no se lleva por delante la terminal. Sin la opción,
`Progreso(None)` no hace nada.
"""
import json
import time
from pathlib import Path
from typing import Any, Optional


class Progreso:
    def __init__(self, ruta: Optional[Path]):
        self.ruta = Path(ruta) if ruta else None
        if self.ruta:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, tipo: str, **datos: Any) -> None:
        if not self.ruta:
            return
        with open(self.ruta, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "tipo": tipo, **datos}, ensure_ascii=False) + "\n")

    def avance(self, etapa: str):
        """Una función `(hechas, total)` para `comun.logits_crudos` que informa de cada lote."""
        return lambda hechas, total: self("avance", etapa=etapa, hechas=hechas, total=total)
