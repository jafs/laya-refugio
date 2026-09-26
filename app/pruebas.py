"""Pruebas propias del modo libre: se guardan como JSON en mis-pruebas/ (fuera de git).

Cada prueba es un fichero `<id>.json` con el mismo formato que los ejemplos de ejemplos/, así que
copiar una prueba propia a ejemplos/ la convierte en un ejemplo fijo más.
"""
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

RAIZ = Path(__file__).resolve().parent.parent
ID_VALIDO = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def carpeta() -> Path:
    """Se lee en cada llamada para que los tests puedan cambiarla con LAYA_MIS_PRUEBAS."""
    return Path(os.environ.get("LAYA_MIS_PRUEBAS") or RAIZ / "mis-pruebas")


class Prueba(BaseModel):
    titulo: str = Field(min_length=1, max_length=80)
    resumen: str = Field(default="", max_length=600)
    modo: Literal["predict", "horda"] = "predict"
    state: Any = None
    states: Optional[List[Any]] = Field(default=None, max_length=512)
    questions: Dict[str, Dict[str, Any]] = Field(min_length=1)
    umbral: Optional[Dict[str, Any]] = None
    question_id: Optional[str] = None

    @model_validator(mode="after")
    def estado_segun_modo(self):
        if self.modo == "horda" and not self.states:
            raise ValueError("una prueba de horda necesita al menos un estado en 'states'")
        if self.modo == "predict" and self.state in (None, ""):
            raise ValueError("una prueba necesita un estado en 'state'")
        return self


def crear_id(titulo: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", sin_tildes.lower()).strip("-")[:50].strip("-") or "prueba"
    candidato, n = base, 2
    while (carpeta() / f"{candidato}.json").exists():
        candidato, n = f"{base}-{n}", n + 1
    return candidato


def _ruta(id_prueba: str) -> Path:
    if not ID_VALIDO.match(id_prueba):
        raise ValueError(f"Identificador de prueba no válido: {id_prueba!r}")
    return carpeta() / f"{id_prueba}.json"


def listar() -> List[Dict[str, Any]]:
    if not carpeta().is_dir():
        return []
    pruebas = []
    for fichero in carpeta().glob("*.json"):
        try:
            with open(fichero, encoding="utf-8") as f:
                datos = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue   # un fichero roto no debe tumbar la terminal
        datos.update(id=fichero.stem, propio=True)
        pruebas.append(datos)
    return sorted(pruebas, key=lambda p: str(p.get("titulo", "")).lower())


def guardar(prueba: Prueba, id_prueba: Optional[str] = None) -> Dict[str, Any]:
    """Crea una prueba nueva (sin id) o sobrescribe una existente (con id)."""
    if id_prueba is None:
        id_prueba = crear_id(prueba.titulo)
    elif not _ruta(id_prueba).exists():
        raise FileNotFoundError(id_prueba)
    datos = prueba.model_dump(exclude_none=True)
    datos.pop("states" if prueba.modo == "predict" else "state", None)
    carpeta().mkdir(parents=True, exist_ok=True)
    with open(_ruta(id_prueba), "w", encoding="utf-8", newline="\n") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return {**datos, "id": id_prueba, "propio": True}


def borrar(id_prueba: str) -> None:
    ruta = _ruta(id_prueba)
    if not ruta.exists():
        raise FileNotFoundError(id_prueba)
    ruta.unlink()
