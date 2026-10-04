"""Tests de los entrenamientos lanzados desde la web, con scripts falsos que no cargan ningún modelo."""
import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

from app.entrenos import Entrenos, Orden, cerebros_disponibles, resumir
from app.main import crear_app

# Un «entrenamiento» de mentira: escribe los mismos eventos que lora.py y termina.
LORA_FALSA = '''
import argparse, json, time
p = argparse.ArgumentParser()
for opcion in ("--progreso", "--nombre", "--epocas", "--rango", "--dispositivo", "--max-casos"):
    p.add_argument(opcion)
p.add_argument("--sin-barajar", action="store_true")
a = p.parse_args()
def ev(tipo, **d):
    with open(a.progreso, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "tipo": tipo, **d}) + "\\n")
ev("inicio", script="lora", modelo=a.nombre)
for i in range(1, 5):
    ev("lote", epoca=1, lote=i, lotes=4, perdida=1.0 / i, media=0.5, s_lote=0.01)
ev("epoca", epoca=1, perdida=0.5, aciertos=0.9, nll=0.3, ece=0.05, segundos=1)
ev("fin", exportado="modelos/" + a.nombre, mejor_epoca=1, memoria_gpu_mb=None, minutos=0.1)
print("hecho")
'''


@pytest.fixture
def raiz(tmp_path):
    (tmp_path / "entrenamiento").mkdir()
    (tmp_path / "entrenamiento" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "entrenamiento" / "lora.py").write_text(LORA_FALSA, encoding="utf-8")
    (tmp_path / "entrenamiento" / "calibrar.py").write_text("import sys; sys.exit(3)", encoding="utf-8")
    return tmp_path


def esperar(entrenos, segundos=20):
    limite = time.time() + segundos
    while entrenos.en_curso and time.time() < limite:
        time.sleep(0.1)
    return entrenos.estado()


def test_resumir_eventos():
    eventos = [{"tipo": "inicio"}, {"tipo": "fase", "texto": "cargando"},
               {"tipo": "avance", "etapa": "x", "hechas": 3, "total": 9}]
    eventos += [{"tipo": "lote", "epoca": 1, "lote": i, "lotes": 400, "perdida": 1.0} for i in range(1, 401)]
    eventos += [{"tipo": "epoca", "epoca": 1, "aciertos": 0.9}, {"tipo": "fin", "exportado": "m"}]
    r = resumir(eventos)
    assert r["fase"] == "cargando" and r["avance"]["hechas"] == 3
    assert r["lote"]["lote"] == 400
    assert 1 < len(r["curva"]) <= 160 and r["curva"][0] == 1.0
    assert r["epocas"][0]["aciertos"] == 0.9 and r["fin"]["exportado"] == "m"


def test_cerebros_disponibles(tmp_path):
    assert [c["id"] for c in cerebros_disponibles(tmp_path)] == ["original"]
    (tmp_path / "modelos" / "lora-a").mkdir(parents=True)
    (tmp_path / "modelos" / "lora-a" / "rl_agent_config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "modelos" / "basura").mkdir()      # sin rl_agent_config.json: no cuenta
    (tmp_path / "calibracion").mkdir()
    (tmp_path / "calibracion" / "lora-a.json").write_text("{}", encoding="utf-8")
    cerebros = {c["id"]: c for c in cerebros_disponibles(tmp_path)}
    assert set(cerebros) == {"original", "lora-a"}
    assert cerebros["lora-a"]["calibracion"] == "calibracion/lora-a.json"
    assert cerebros["original"]["calibracion"] is None


def test_comando_valida_nombres_y_calibracion(raiz):
    e = Entrenos(raiz)
    with pytest.raises(ValueError):
        e.comando(Orden(tipo="lora", modelo="../fuera"), raiz / "p.jsonl")
    with pytest.raises(ValueError):
        e.comando(Orden(tipo="lora", modelo="original"), raiz / "p.jsonl")
    with pytest.raises(ValueError, match="calibración"):
        e.comando(Orden(tipo="evaluar", modelo="original", calibrado=True), raiz / "p.jsonl")
    with pytest.raises(ValueError, match="No hay"):
        e.comando(Orden(tipo="calibrar", modelo="inventado"), raiz / "p.jsonl")
    comando = e.comando(Orden(tipo="lora", modelo="lora-b", epocas=2, max_casos=40, barajar=False), raiz / "p.jsonl")
    assert comando[:3] == [sys.executable, "-m", "entrenamiento.lora"]
    assert ["--max-casos", "40"] == comando[comando.index("--max-casos"):][:2] and "--sin-barajar" in comando


def test_lanzar_y_seguir_un_trabajo(raiz):
    e = Entrenos(raiz)
    assert e.estado() == {"estado": "nada"}
    e.lanzar(Orden(tipo="lora", modelo="lora-b", epocas=1))
    with pytest.raises(RuntimeError):
        if e.en_curso:
            e.lanzar(Orden(tipo="lora", modelo="lora-c"))
        else:
            raise RuntimeError("terminó antes de poder probarlo")
    estado = esperar(e)
    assert estado["estado"] == "terminado", estado["registro"]
    assert estado["fin"]["exportado"] == "modelos/lora-b"
    assert estado["lote"]["lote"] == 4 and len(estado["epocas"]) == 1
    assert "hecho" in estado["registro"]
    # Otra instancia (el servidor reiniciado) sigue viendo el último trabajo.
    assert Entrenos(raiz).estado()["estado"] == "terminado"


def test_trabajo_que_falla(raiz):
    e = Entrenos(raiz)
    e.lanzar(Orden(tipo="calibrar", modelo="original", dispositivo="cpu"))
    assert esperar(e)["estado"] == "error"


class CerebroCambiable:
    listo = True

    def __init__(self):
        self.cambios = []

    def estado(self):
        return {"fase": "listo", "listo": True, "cerebro": "original", "calibracion": None,
                "cambio": {"en_curso": False, "error": None}}

    def cambiar(self, modelo, calibracion):
        self.cambios.append((modelo, calibracion))


def test_api_entrenamiento_y_cerebros(raiz):
    cerebro = CerebroCambiable()
    cliente = TestClient(crear_app(cerebro, Entrenos(raiz)))
    assert cliente.get("/api/training").json() == {"estado": "nada"}
    assert cliente.post("/api/training", json={"tipo": "lora", "modelo": "MAL NOMBRE"}).status_code == 400
    assert cliente.post("/api/training", json={"tipo": "lora", "epocas": 99}).status_code == 422

    datos = cliente.get("/api/brains").json()
    assert datos["activo"] == "original" and [c["id"] for c in datos["cerebros"]] == ["original"]
    assert cliente.post("/api/brain", json={"cerebro": "original", "calibrado": True}).status_code == 400
    assert cliente.post("/api/brain", json={"cerebro": "no-existe"}).status_code == 400
    assert cliente.post("/api/brain", json={"cerebro": "original"}).status_code == 200
    assert cerebro.cambios == [(None, None)]


def test_estado_del_cerebro_incluye_el_activo():
    from app.cerebro import Cerebro

    estado = Cerebro(["multilingual"]).estado()
    assert estado["cerebro"] == "original" and estado["cambio"]["en_curso"] is False
