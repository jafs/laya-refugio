"""Terminal del refugio: servidor FastAPI que expone el cerebro de Laya a la web de static/."""
import json
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import pruebas

RAIZ = Path(__file__).resolve().parent.parent
ESTATICOS = RAIZ / "static"
EJEMPLOS = RAIZ / "ejemplos"


def cerebro_desde_entorno():
    from .cerebro import Cerebro

    checkpoints = [c.strip() for c in os.environ.get("LAYA_CHECKPOINTS", "multilingual").split(",") if c.strip()]
    return Cerebro(
        checkpoints=checkpoints,
        defecto=os.environ.get("LAYA_DEFAULT", checkpoints[0]),
        dispositivo=os.environ.get("LAYA_DEVICE", "auto").strip() or "auto",
        precision=os.environ.get("LAYA_PRECISION", "auto").strip() or "auto",
    )


def cargar_ejemplos() -> List[Dict[str, Any]]:
    ejemplos = []
    for fichero in sorted(EJEMPLOS.glob("*.json")):
        with open(fichero, encoding="utf-8") as f:
            ejemplo = json.load(f)
        ejemplo.setdefault("id", fichero.stem)
        ejemplo["propio"] = False
        ejemplos.append(ejemplo)
    return ejemplos


class Peticion(BaseModel):
    state: Any
    questions: Dict[str, Dict[str, Any]]
    model: Optional[str] = None


class PeticionHorda(BaseModel):
    states: List[Any] = Field(min_length=1, max_length=512)
    questions: Dict[str, Dict[str, Any]]
    model: Optional[str] = None
    comparar: bool = True


class PeticionBarajar(Peticion):
    question_id: str
    rondas: int = Field(default=6, ge=2, le=24)
    semilla: Optional[int] = None


def crear_app(cerebro=None) -> FastAPI:
    """`cerebro` se inyecta en los tests; si no se pasa, se crea a partir de las variables de entorno."""

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        modelo_real = app.state.cerebro is None
        if modelo_real:
            app.state.cerebro = cerebro_desde_entorno()
            app.state.cerebro.arrancar()
        yield
        if modelo_real:
            # Red de seguridad: si algo nativo (torch, CUDA, los hilos de descarga) impide que el
            # intérprete termine, el proceso se cierra igualmente y suelta la VRAM.
            guardian = threading.Timer(5, os._exit, args=(0,))
            guardian.daemon = True
            guardian.start()

    app = FastAPI(title="Terminal del refugio", lifespan=ciclo_de_vida)
    app.state.cerebro = cerebro

    def cerebro_listo():
        c = app.state.cerebro
        if c is None or not c.listo:
            estado = c.estado() if c else {"fase": "arrancando"}
            if estado.get("fase") == "error":
                raise HTTPException(500, f"El cerebro no ha podido cargar: {estado.get('error')}")
            raise HTTPException(503, f"El cerebro todavía no está listo (fase: {estado.get('fase')})")
        return c

    def ejecutar(funcion, *args, **kwargs):
        try:
            return funcion(*args, **kwargs)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/status")
    def status() -> Dict[str, Any]:
        c = app.state.cerebro
        return c.estado() if c else {"fase": "arrancando", "listo": False}

    @app.get("/api/examples")
    def examples() -> List[Dict[str, Any]]:
        """Los ejemplos fijos del repositorio y, detrás, las pruebas propias del modo libre."""
        return cargar_ejemplos() + pruebas.listar()

    @app.post("/api/custom")
    def crear_prueba(p: pruebas.Prueba) -> Dict[str, Any]:
        return pruebas.guardar(p)

    @app.put("/api/custom/{id_prueba}")
    def actualizar_prueba(id_prueba: str, p: pruebas.Prueba) -> Dict[str, Any]:
        try:
            return pruebas.guardar(p, id_prueba)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, f"No existe la prueba {id_prueba!r}") from exc

    @app.delete("/api/custom/{id_prueba}")
    def borrar_prueba(id_prueba: str) -> Dict[str, Any]:
        try:
            pruebas.borrar(id_prueba)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, f"No existe la prueba {id_prueba!r}") from exc
        return {"borrada": id_prueba}

    @app.post("/api/predict")
    def predict(p: Peticion) -> Dict[str, Any]:
        if not p.questions:
            raise HTTPException(400, "Hace falta al menos una pregunta")
        return ejecutar(cerebro_listo().predecir, p.state, p.questions, p.model)

    @app.post("/api/horde")
    def horde(p: PeticionHorda) -> Dict[str, Any]:
        if not p.questions:
            raise HTTPException(400, "Hace falta al menos una pregunta")
        return ejecutar(cerebro_listo().horda, p.states, p.questions, p.model, p.comparar)

    @app.post("/api/permute")
    def permute(p: PeticionBarajar) -> Dict[str, Any]:
        return ejecutar(cerebro_listo().barajar, p.state, p.questions, p.question_id,
                        p.rondas, p.model, p.semilla)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(ESTATICOS / "index.html")

    app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")
    return app


app = crear_app()
