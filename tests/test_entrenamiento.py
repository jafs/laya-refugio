"""Tests de entrenamiento/ que no cargan el modelo: LoRA, temperaturas, datos y calibración."""
import json
import random
import types

import numpy as np
import pytest
import torch
from torch import nn

from app.cerebro import Cerebro, _aplicar_calibracion, _leer_calibracion
from entrenamiento import comun, generar_datos
from entrenamiento.lora import LoRALinear, fusionar, inyectar


class Capa(nn.Module):
    def __init__(self):
        super().__init__()
        self.Wqkv = nn.Linear(6, 9)
        self.norma = nn.LayerNorm(9)
        self.Wo = nn.Linear(9, 6)

    def forward(self, x):
        return self.Wo(self.norma(self.Wqkv(x)))


class Red(nn.Module):
    def __init__(self):
        super().__init__()
        self.capas = nn.ModuleList([Capa(), Capa()])
        self.salida = nn.Linear(6, 1)   # no está en los objetivos: se queda como está

    def forward(self, x):
        for c in self.capas:
            x = c(x)
        return self.salida(x)


def test_lora_empieza_siendo_el_modelo_original():
    torch.manual_seed(0)
    red, x = Red(), torch.randn(4, 6)
    antes = red(x)
    envueltas = inyectar(red, ["Wqkv", "Wo"], r=2, alpha=4, dropout=0.0)
    assert envueltas == ["capas.0.Wqkv", "capas.0.Wo", "capas.1.Wqkv", "capas.1.Wo"]
    assert torch.allclose(red(x), antes)


def test_solo_se_entrenan_las_matrices_lora():
    red = Red()
    red.requires_grad_(False)
    inyectar(red, ["Wqkv", "Wo"], r=2, alpha=4, dropout=0.0)
    entrenables = [n for n, p in red.named_parameters() if p.requires_grad]
    assert entrenables and all(n.endswith((".A", ".B")) for n in entrenables)


def test_fusionar_da_lo_mismo_y_deja_nn_linear():
    torch.manual_seed(1)
    red, x = Red(), torch.randn(4, 6)
    inyectar(red, ["Wqkv", "Wo"], r=2, alpha=4, dropout=0.0)
    for m in red.modules():
        if isinstance(m, LoRALinear):
            nn.init.normal_(m.B)
    con_lora = red(x)
    claves_antes = set(Red().state_dict())
    fusionar(red)
    assert not any(isinstance(m, LoRALinear) for m in red.modules())
    assert set(red.state_dict()) == claves_antes
    assert torch.allclose(red(x), con_lora, atol=1e-5)


def test_indice_respuesta():
    choice = {"type": "choice", "criteria": {"atacar": "a", "seguir": "b"}}
    assert comun.indice_respuesta(choice, "seguir") == 1
    assert comun.indice_respuesta({"type": "score", "criteria": ["x", "y", "z"]}, 2) == 2
    assert comun.indice_respuesta({"type": "noul"}, True) == 1
    assert comun.indice_respuesta({"type": "noul"}, False) == 0
    with pytest.raises(ValueError):
        comun.indice_respuesta(choice, "trepar")
    with pytest.raises(ValueError):
        comun.indice_respuesta({"type": "noul"}, "true")


def test_barajar_caso_solo_mueve_las_choice():
    caso = {"questions": {
        "accion": {"type": "choice", "instructions": "?", "criteria": {"a": "1", "b": "2", "c": "3", "d": "4"}},
        "hambre": {"type": "score", "instructions": "?", "criteria": ["0", "1", "2"]},
    }, "respuestas": {"accion": "c", "hambre": 2}}
    ordenes = {tuple(comun.barajar_caso(caso, random.Random(s))["questions"]["accion"]["criteria"])
               for s in range(20)}
    assert len(ordenes) > 1
    barajado = comun.barajar_caso(caso, random.Random(3))
    assert barajado["questions"]["hambre"] == caso["questions"]["hambre"]
    assert barajado["questions"]["accion"]["criteria"]["c"] == "3"


def registros_sinteticos(t_real: float, n: int = 3000, k: int = 3, semilla: int = 0):
    """Logits cuyo reparto verdadero es softmax(z / t_real): la temperatura ideal es t_real."""
    azar = np.random.default_rng(semilla)
    registros = []
    for _ in range(n):
        z = azar.normal(0, 3, size=k)
        etiqueta = int(azar.choice(k, p=comun.softmax(z / t_real)))
        registros.append(comun.Registro("q", 0, k, z, etiqueta))
    return registros


def test_ajustar_temperatura_recupera_la_real():
    assert comun.ajustar_temperatura(registros_sinteticos(2.0)) == pytest.approx(2.0, rel=0.1)


def test_calibrar_baja_el_ece_y_no_cambia_aciertos():
    registros = registros_sinteticos(2.5)
    ajuste = comun.calibrar(registros)
    antes, despues = comun.metricas(registros)["total"], comun.metricas(registros, ajuste)["total"]
    assert despues["aciertos"] == antes["aciertos"]
    assert despues["ece"] < antes["ece"] / 2


def test_cubetas_pequenas_heredan_la_del_tipo():
    registros = registros_sinteticos(2.0, n=100, k=3) + registros_sinteticos(2.0, n=10, k=7, semilla=1)
    ajuste = comun.calibrar(registros, minimo_cubeta=30)
    assert list(ajuste["temperature_by_options"]) == ["choice:3-5"]
    sola = comun.Registro("q", 0, 7, np.zeros(7), 0)
    assert comun.temperatura_de(sola, ajuste) == ajuste["temperature"][0]


def test_generador_coherente_y_sin_frases_no_vistas_al_entrenar():
    for caso in generar_datos.generar(200, "entrenamiento", semilla=5):
        r = caso["respuestas"]
        for qid, respuesta in r.items():
            comun.indice_respuesta(caso["questions"][qid], respuesta)   # etiqueta válida
        if caso["dominio"] == "zombi":
            assert r["humano_cerca"] == (r["accion"] in ("atacar", "seguir"))
            assert r["hambre"] == {"atacar": 2, "seguir": 1}.get(r["accion"], 0)
            assert caso["state"]["olor"] not in generar_datos.OLOR_INTENSO[1::2]
        else:
            assert not r["mordedura"] or r["decision"] == "rechazar"
            assert caso["state"]["heridas"] not in generar_datos.HERIDA_SIN_EXPLICAR[1::2]


def test_casos_del_articulo_existen():
    casos = generar_datos.casos_articulo()
    assert len(casos) == len(generar_datos.ETIQUETAS_ARTICULO)


def test_leer_y_aplicar_calibracion(tmp_path):
    ruta = tmp_path / "cal.json"
    ruta.write_text(json.dumps({"temperature": [2.0, 9.0, 0.1],
                                "temperature_by_options": {"choice:3-5": 1.7}}), encoding="utf-8")
    cal = _leer_calibracion(str(ruta))
    assert cal["checkpoint"] == "multilingual"
    agente = types.SimpleNamespace(temperature=[1, 1, 1], temperature_by_options={})
    _aplicar_calibracion(agente, cal)
    assert agente.temperature == [2.0, 5.0, 0.5]          # recortadas a [0.5, 5] como hace Laya
    assert agente.temperature_by_options == {"choice:3-5": 1.7}

    ruta.write_text(json.dumps({"temperature": [1.0]}), encoding="utf-8")
    with pytest.raises(ValueError):
        _leer_calibracion(str(ruta))


def test_cerebro_rechaza_modelo_local_que_no_es_de_laya(tmp_path):
    with pytest.raises(ValueError, match="rl_agent_config"):
        Cerebro(["multilingual"], modelos_locales={"multilingual": str(tmp_path)})
