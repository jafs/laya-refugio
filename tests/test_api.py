"""Tests de la API con un cerebro falso: no descargan ni cargan ningún modelo."""
import pytest
from fastapi.testclient import TestClient

from app.cerebro import barajar, ordenes_barajados
from app.main import cargar_ejemplos, crear_app

PREGUNTAS = {
    "accion": {
        "type": "choice",
        "instructions": "¿Qué hace el zombi?",
        "criteria": {"atacar": "humano cerca", "seguir": "rastro lejano", "vagar": "nada"},
    }
}


def predecir_primera(estado, preguntas):
    """Imita a un modelo muy sensible al orden: siempre elige la primera opción."""
    respuestas = {}
    for qid, q in preguntas.items():
        claves = list(q["criteria"])
        respuestas[qid] = {"choice": claves[0], "probabilities": {k: 1 / len(claves) for k in claves}}
    return {"answers": respuestas}


class CerebroFalso:
    def __init__(self, listo=True):
        self.listo = listo

    def estado(self):
        return {"fase": "listo" if self.listo else "cargando", "listo": self.listo}

    def predecir(self, estado, preguntas, modelo=None):
        return {**predecir_primera(estado, preguntas), "latency_ms": 1.0}

    def horda(self, estados, preguntas, modelo=None, comparar=True):
        return {"resultados": [predecir_primera(e, preguntas) for e in estados], "lote_ms": 1.0}

    def barajar(self, estado, preguntas, id_pregunta, rondas=6, modelo=None, semilla=None):
        return barajar(predecir_primera, estado, preguntas, id_pregunta, rondas, semilla)


@pytest.fixture
def cliente():
    return TestClient(crear_app(CerebroFalso()))


def test_status(cliente):
    assert cliente.get("/api/status").json()["listo"] is True


def test_predict(cliente):
    r = cliente.post("/api/predict", json={"state": "olor a humano", "questions": PREGUNTAS})
    assert r.status_code == 200
    assert r.json()["answers"]["accion"]["choice"] == "atacar"


def test_predict_sin_preguntas(cliente):
    assert cliente.post("/api/predict", json={"state": "x", "questions": {}}).status_code == 400


def test_predict_mientras_carga():
    cliente = TestClient(crear_app(CerebroFalso(listo=False)))
    r = cliente.post("/api/predict", json={"state": "x", "questions": PREGUNTAS})
    assert r.status_code == 503


def test_horda(cliente):
    r = cliente.post("/api/horde", json={"states": ["a", "b", "c"], "questions": PREGUNTAS})
    assert r.status_code == 200
    assert len(r.json()["resultados"]) == 3


def test_barajar_detecta_sensibilidad_al_orden(cliente):
    r = cliente.post("/api/permute", json={
        "state": "olor a humano", "questions": PREGUNTAS, "question_id": "accion", "rondas": 4, "semilla": 1,
    })
    datos = r.json()
    assert r.status_code == 200
    assert datos["estable"] is False
    assert [r["eleccion"] for r in datos["resultados"]] == [o["orden"][0] for o in datos["resultados"]]


def test_barajar_rechaza_preguntas_que_no_son_choice(cliente):
    preguntas = {"humano": {"type": "noul", "instructions": "¿Hay humano?"}}
    r = cliente.post("/api/permute", json={"state": "x", "questions": preguntas, "question_id": "humano"})
    assert r.status_code == 400


def test_ordenes_barajados_incluye_original_e_invertido():
    import random

    ordenes = ordenes_barajados(["a", "b", "c"], 5, random.Random(0))
    assert ordenes[0] == ["a", "b", "c"]
    assert ordenes[1] == ["c", "b", "a"]
    assert len(ordenes) == len({tuple(o) for o in ordenes}) == 5


def test_ejemplos_validos():
    ejemplos = cargar_ejemplos()
    assert ejemplos
    for e in ejemplos:
        assert {"id", "titulo", "modo"} <= set(e)
        assert e["questions"]


# ------------------------------------------------------------------ modo libre
PRUEBA = {"titulo": "Mi zombi de prueba", "resumen": "Uno que solo come coles",
          "state": {"olor": "coles"}, "questions": PREGUNTAS}


@pytest.fixture
def cliente_libre(tmp_path, monkeypatch):
    monkeypatch.setenv("LAYA_MIS_PRUEBAS", str(tmp_path / "mis-pruebas"))
    return TestClient(crear_app(CerebroFalso()))


def test_crear_listar_y_borrar_prueba(cliente_libre):
    creada = cliente_libre.post("/api/custom", json=PRUEBA).json()
    assert creada["id"] == "mi-zombi-de-prueba" and creada["propio"] is True

    todas = cliente_libre.get("/api/examples").json()
    assert [e["id"] for e in todas if e["propio"]] == ["mi-zombi-de-prueba"]
    assert all(e["propio"] is False for e in todas if e["id"] != "mi-zombi-de-prueba")

    assert cliente_libre.delete("/api/custom/mi-zombi-de-prueba").status_code == 200
    assert not [e for e in cliente_libre.get("/api/examples").json() if e["propio"]]


def test_titulos_repetidos_no_se_pisan(cliente_libre):
    a = cliente_libre.post("/api/custom", json=PRUEBA).json()["id"]
    b = cliente_libre.post("/api/custom", json=PRUEBA).json()["id"]
    assert (a, b) == ("mi-zombi-de-prueba", "mi-zombi-de-prueba-2")


def test_sobrescribir_prueba(cliente_libre):
    id_prueba = cliente_libre.post("/api/custom", json=PRUEBA).json()["id"]
    r = cliente_libre.put(f"/api/custom/{id_prueba}", json={**PRUEBA, "resumen": "Ahora come de todo"})
    assert r.status_code == 200
    propia = [e for e in cliente_libre.get("/api/examples").json() if e["propio"]][0]
    assert propia["resumen"] == "Ahora come de todo"


def test_prueba_de_horda_guarda_solo_states(cliente_libre):
    horda = {**PRUEBA, "modo": "horda", "states": [{"olor": "coles"}, {"olor": "nada"}]}
    creada = cliente_libre.post("/api/custom", json=horda).json()
    assert "state" not in creada and len(creada["states"]) == 2


def test_validaciones_modo_libre(cliente_libre):
    assert cliente_libre.post("/api/custom", json={**PRUEBA, "titulo": ""}).status_code == 422
    assert cliente_libre.post("/api/custom", json={**PRUEBA, "modo": "horda"}).status_code == 422
    assert cliente_libre.put("/api/custom/no-existe", json=PRUEBA).status_code == 404
    assert cliente_libre.delete("/api/custom/..%2Fapp%2Fmain").status_code in (400, 404)
    assert cliente_libre.delete("/api/custom/Nombre_Raro").status_code == 400
