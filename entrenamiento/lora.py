"""Especializa a Laya con LoRA: congela el modelo y entrena solo unas matrices pequeñas al lado.

LoRA (Low-Rank Adaptation) no toca los pesos originales. A cada capa lineal elegida le añade un
desvío `B @ A`, dos matrices estrechas de rango r (8 por defecto), y solo se entrenan esas. En el
multilingüe son unos 3 millones de parámetros de 322: cabe sin problemas en una GTX 1660 y se
puede (despacio) hasta en CPU. Al terminar, el desvío se suma a los pesos y sale un checkpoint
normal de Laya, que se carga igual que el original.

Durante el entrenamiento se barajan las opciones de cada pregunta `choice`, para que el modelo no
pueda apoyarse en la posición de la respuesta (el sesgo de orden del artículo).

Uso:
    python -m entrenamiento.lora                          # GPU si hay, si no CPU
    python -m entrenamiento.lora --dispositivo cpu --epocas 1
    python -m entrenamiento.lora --nombre lora-prueba --max-casos 40   # ensayo rápido

Deja el checkpoint en modelos/<nombre>/. Después conviene calibrarlo:
    python -m entrenamiento.calibrar --modelo modelos/lora-refugio
y para usarlo en la terminal:
    LAYA_MODELO_MULTILINGUAL=modelos/lora-refugio LAYA_CALIBRACION=calibracion/lora-refugio.json ./run.sh
"""
import argparse
import json
import math
import random
import shutil
import time
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List

import torch
from torch import nn

from . import comun
from .progreso import Progreso

# Capas lineales del encoder (ModernBERT/mmBERT). La cabeza de decisión de Laya no se toca: es un
# nn.TransformerEncoderLayer, que en inferencia lee `linear1.weight` y compañía directamente y se
# saltaría el desvío de LoRA.
OBJETIVOS = ("Wqkv", "Wo", "Wi")


class LoRALinear(nn.Module):
    """Una nn.Linear congelada más un desvío entrenable de rango r: W·x + (alpha/r)·B·A·x."""

    def __init__(self, base: nn.Linear, r: int, alpha: float, dropout: float):
        super().__init__()
        self.base = base
        self.base.requires_grad_(False)
        self.escala = alpha / r
        self.A = nn.Parameter(torch.empty(r, base.in_features, device=base.weight.device))
        # B empieza a cero: el modelo arranca siendo exactamente el original.
        self.B = nn.Parameter(torch.zeros(base.out_features, r, device=base.weight.device))
        nn.init.kaiming_uniform_(self.A, a=math.sqrt(5))
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.base(x) + (self.dropout(x) @ self.A.T @ self.B.T) * self.escala

    @torch.no_grad()
    def fusionar(self) -> nn.Linear:
        """Suma el desvío a los pesos y devuelve la nn.Linear de siempre."""
        self.base.weight += (self.B @ self.A).to(self.base.weight.dtype) * self.escala
        return self.base


def inyectar(modelo: nn.Module, objetivos: Iterable[str], r: int, alpha: float, dropout: float) -> List[str]:
    """Envuelve con LoRALinear cada nn.Linear cuyo nombre esté en `objetivos`."""
    objetivos = set(objetivos)
    envueltas = []
    for nombre_padre, padre in list(modelo.named_modules()):
        for nombre, hijo in list(padre.named_children()):
            if nombre in objetivos and type(hijo) is nn.Linear:
                setattr(padre, nombre, LoRALinear(hijo, r, alpha, dropout))
                envueltas.append(f"{nombre_padre}.{nombre}" if nombre_padre else nombre)
    return envueltas


def fusionar(modelo: nn.Module) -> None:
    """Sustituye cada LoRALinear por su nn.Linear con el desvío ya sumado."""
    for padre in list(modelo.modules()):
        for nombre, hijo in list(padre.named_children()):
            if isinstance(hijo, LoRALinear):
                setattr(padre, nombre, hijo.fusionar())


def entrenables(modelo: nn.Module) -> Dict[str, torch.Tensor]:
    return {n: p.detach().cpu().clone() for n, p in modelo.named_parameters() if p.requires_grad}


def exportar(agente, origen: str, destino: Path, info: Dict, fusionadas: Iterable[str] = ()) -> None:
    """Escribe un checkpoint de Laya completo: pesos fusionados, configuración y tokenizer.

    `fusionadas` son las capas que llevaban LoRA: sus pesos se guardan en fp32, porque en fp16 el
    redondeo podría comerse buena parte de un desvío tan pequeño.
    """
    from safetensors import safe_open
    from safetensors.torch import save_file

    destino.mkdir(parents=True, exist_ok=True)
    # El resto de tensores vuelve al tipo con el que venía (fp16 casi todos), para ocupar lo mismo.
    with safe_open(str(Path(origen) / "model.safetensors"), "pt") as f:
        tipos = {k: f.get_slice(k).get_dtype() for k in f.keys()}
    tipos.update({f"{capa}.weight": "F32" for capa in fusionadas})
    conversion = {"F16": torch.float16, "BF16": torch.bfloat16, "F32": torch.float32}
    estado = {k: v.detach().to("cpu", conversion.get(tipos.get(k), torch.float32)).contiguous()
              for k, v in agente.model.state_dict().items()}
    save_file(estado, str(destino / "model.safetensors"), metadata={"format": "pt"})

    for carpeta in ("tokenizer", "encoder"):
        if (Path(origen) / carpeta).is_dir():
            shutil.copytree(Path(origen) / carpeta, destino / carpeta, dirs_exist_ok=True)
    with open(Path(origen) / "rl_agent_config.json", encoding="utf-8") as f:
        cfg = json.load(f)
    # Las temperaturas del original no valen para el modelo nuevo: se calibran aparte.
    cfg["temperature"] = [1.0, 1.0, 1.0]
    cfg["temperature_by_options"] = {}
    cfg["lora"] = info
    comun.guardar_json(destino / "rl_agent_config.json", cfg)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--checkpoint", default="multilingual", choices=["multilingual", "english"])
    p.add_argument("--dispositivo", default="auto", help="auto (cuda si hay), cuda, cpu...")
    p.add_argument("--datos", type=Path, default=comun.DATOS / "entrenamiento.jsonl")
    p.add_argument("--validacion", type=Path, default=comun.DATOS / "validacion.jsonl")
    p.add_argument("--nombre", default="lora-refugio", help="carpeta de salida dentro de modelos/")
    p.add_argument("--rango", type=int, default=8, help="r: anchura de las matrices A y B")
    p.add_argument("--alpha", type=float, default=16.0)
    p.add_argument("--dropout", type=float, default=0.05)
    p.add_argument("--objetivos", default=",".join(OBJETIVOS), help="capas lineales a envolver")
    p.add_argument("--epocas", type=int, default=3)
    p.add_argument("--lote", type=int, default=8, help="filas (pregunta + estado) por pasada")
    p.add_argument("--acumulacion", type=int, default=2, help="pasadas por paso del optimizador")
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--sin-barajar", action="store_true", help="no barajar las opciones al entrenar")
    p.add_argument("--checkpointing", action="store_true",
                   help="gradient checkpointing en el encoder: menos memoria, algo más lento")
    p.add_argument("--max-casos", type=int, help="usar solo los primeros N casos (para ensayos)")
    p.add_argument("--semilla", type=int, default=1)
    p.add_argument("--progreso", type=Path, help="fichero JSONL de eventos para la terminal web")
    a = p.parse_args()
    progreso = Progreso(a.progreso)
    progreso("inicio", script="lora", modelo=a.nombre, epocas=a.epocas, rango=a.rango,
             barajar=not a.sin_barajar)

    torch.manual_seed(a.semilla)
    azar = random.Random(a.semilla)
    dispositivo = a.dispositivo
    if dispositivo == "auto":
        dispositivo = "cuda" if torch.cuda.is_available() else "cpu"

    casos = comun.leer_jsonl(a.datos)[:a.max_casos]
    validacion = comun.leer_jsonl(a.validacion)[:a.max_casos]

    progreso("fase", texto="cargando el modelo")
    origen = comun.ruta_checkpoint(a.checkpoint)
    agente = comun.cargar_agente(origen, dispositivo=dispositivo)
    modelo = agente.model
    modelo.requires_grad_(False)
    envueltas = inyectar(modelo, a.objetivos.split(","), a.rango, a.alpha, a.dropout)
    if not envueltas:
        raise SystemExit(f"Ninguna capa coincide con {a.objetivos}")
    if a.checkpointing:
        modelo.encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    n_total = sum(p.numel() for p in modelo.parameters())
    n_lora = sum(p.numel() for p in modelo.parameters() if p.requires_grad)
    print(f"Dispositivo: {agente.device} | capas con LoRA: {len(envueltas)} | "
          f"parámetros entrenables: {n_lora / 1e6:.2f} M de {n_total / 1e6:.0f} M ({n_lora / n_total:.1%})")
    progreso("modelo", dispositivo=str(agente.device), capas=len(envueltas), entrenables=n_lora,
             total=n_total, casos=len(casos))

    progreso("fase", texto="validación antes de entrenar")
    base = comun.metricas(comun.logits_crudos(agente, validacion,
                                              avance=progreso.avance("validación inicial")))["total"]
    print(f"Validación antes de entrenar: aciertos {base['aciertos']:.1%}, NLL {base['nll']:.3f}")
    progreso("validacion_inicial", **base)

    from laya.common import collate_items

    parametros = [p for p in modelo.parameters() if p.requires_grad]
    optimizador = torch.optim.AdamW(parametros, lr=a.lr, weight_decay=0.0)
    filas_por_epoca = sum(len(c["respuestas"]) for c in casos)
    pasos = max(1, a.epocas * math.ceil(filas_por_epoca / (a.lote * a.acumulacion)))
    planificador = torch.optim.lr_scheduler.OneCycleLR(optimizador, max_lr=a.lr, total_steps=pasos,
                                                       pct_start=0.1)
    if agente.device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(agente.device)

    mejor = {"nll": base["nll"], "epoca": 0, "pesos": entrenables(modelo), "aciertos": base["aciertos"]}
    historial = []
    t_inicio = time.time()
    for epoca in range(1, a.epocas + 1):
        modelo.train()
        filas = [f for caso in casos
                 for f in comun.codificar(agente, caso if a.sin_barajar else comun.barajar_caso(caso, azar))]
        azar.shuffle(filas)
        suma, t0 = 0.0, time.time()
        optimizador.zero_grad(set_to_none=True)
        lotes = range(0, len(filas), a.lote)
        progreso("fase", texto=f"entrenando: época {epoca} de {a.epocas}")
        for i, inicio in enumerate(lotes, 1):
            b = collate_items([filas[inicio:inicio + a.lote]], agente.tok.pad_token_id)
            logits, _ = modelo(*(b[c].to(agente.device) for c in
                                 ("input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype")))
            # Entropía cruzada contra el reparto correcto. Las posiciones de relleno valen -1e4 en
            # los logits y 0 en el objetivo, así que no cuentan.
            perdida = -(b["target"].to(agente.device) * torch.log_softmax(logits, -1)).sum(-1).mean()
            (perdida / a.acumulacion).backward()
            suma += perdida.item()
            if i % a.acumulacion == 0 or i == len(lotes):
                torch.nn.utils.clip_grad_norm_(parametros, 1.0)
                optimizador.step()
                if planificador.last_epoch + 1 < pasos:
                    planificador.step()
                optimizador.zero_grad(set_to_none=True)
            progreso("lote", epoca=epoca, lote=i, lotes=len(lotes), perdida=round(perdida.item(), 5),
                     media=round(suma / i, 5), s_lote=round((time.time() - t0) / i, 3))
            if i % 25 == 0 or i == len(lotes):
                print(f"  época {epoca} | lote {i}/{len(lotes)} | pérdida {suma / i:.4f} | "
                      f"{(time.time() - t0) / i:.2f} s/lote", flush=True)

        progreso("fase", texto=f"validando la época {epoca}")
        val = comun.metricas(comun.logits_crudos(agente, validacion,
                                                 avance=progreso.avance(f"validación de la época {epoca}")))["total"]
        historial.append({"epoca": epoca, "perdida": round(suma / len(lotes), 4), **val})
        progreso("epoca", **historial[-1], segundos=round(time.time() - t0))
        print(f"Época {epoca}: validación aciertos {val['aciertos']:.1%}, NLL {val['nll']:.3f}, "
              f"ECE {val['ece']:.3f} ({time.time() - t0:.0f} s)")
        if val["nll"] < mejor["nll"]:
            mejor = {"nll": val["nll"], "epoca": epoca, "pesos": entrenables(modelo), "aciertos": val["aciertos"]}

    memoria = None
    if agente.device.type == "cuda":
        memoria = round(torch.cuda.max_memory_allocated(agente.device) / 1_048_576)
        print(f"Memoria de GPU máxima: {memoria} MB")

    if mejor["epoca"] == 0:
        print("Ninguna época mejoró la validación: no se exporta nada.")
        progreso("fin", exportado=None, memoria_gpu_mb=memoria,
                 minutos=round((time.time() - t_inicio) / 60, 1))
        return
    progreso("fase", texto="exportando el checkpoint")
    modelo.load_state_dict({**modelo.state_dict(), **{k: v.to(agente.device) for k, v in mejor["pesos"].items()}})
    destino = comun.RAIZ / "modelos" / a.nombre
    destino.mkdir(parents=True, exist_ok=True)
    from safetensors.torch import save_file

    # El adaptador solo (unos MB), por si se quiere aplicar a mano o compartir sin el modelo entero.
    save_file({k: v.contiguous() for k, v in mejor["pesos"].items()}, str(destino / "lora.safetensors"))
    info = {
        "base": a.checkpoint, "fecha": date.today().isoformat(), "rango": a.rango, "alpha": a.alpha,
        "dropout": a.dropout, "objetivos": a.objetivos.split(","), "epocas": a.epocas,
        "mejor_epoca": mejor["epoca"], "lr": a.lr, "lote": a.lote, "acumulacion": a.acumulacion,
        "barajar_opciones": not a.sin_barajar, "casos": len(casos),
        "datos": a.datos.name, "minutos": round((time.time() - t_inicio) / 60, 1),
        "memoria_gpu_mb": memoria, "validacion_inicial": base, "historial": historial,
    }
    comun.guardar_json(destino / "lora.json", info)
    fusionar(modelo)
    exportar(agente, origen, destino, info, envueltas)
    progreso("fin", exportado=f"modelos/{a.nombre}", mejor_epoca=mejor["epoca"], memoria_gpu_mb=memoria,
             minutos=info["minutos"])
    print(f"Checkpoint exportado en modelos/{a.nombre} (mejor época: {mejor['epoca']}). "
          f"Siguiente paso: python -m entrenamiento.calibrar --modelo modelos/{a.nombre}")


if __name__ == "__main__":
    main()
