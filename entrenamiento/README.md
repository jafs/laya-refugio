# Entrenar al cerebro del refugio

Laya sale de fábrica como una base que hay que especializar. Aquí hay dos formas de hacerlo, de menos a más:

1. **Calibrar.** No toca el modelo: ajusta las temperaturas con las que Laya convierte sus puntuaciones en probabilidades. Las respuestas siguen siendo las mismas, pero un 90 % pasa a significar «acierta nueve de cada diez». Va bien en CPU, en pocos minutos.
2. **LoRA.** Congela el modelo y entrena unas matrices pequeñas al lado de sus capas lineales (unos 3 millones de parámetros de 322). Esto sí cambia las respuestas. Cabe en una GPU modesta (una GTX 1660 de 6 GB) y, con paciencia, en CPU.

## Desde la terminal web

Todo lo de abajo se puede hacer también desde la terminal: en el menú, `> entrenar()`. Ahí se elige el cerebro que responde (el original o cualquiera de `modelos/`, con o sin calibrar) sin reiniciar el servidor, y se lanzan `calibrar()`, `entrenarLoRA()` y `evaluar()` viendo el progreso: lotes, curva de pérdida, validación por época y, al final, las tablas de resultados.

Cada trabajo corre en un proceso aparte (si se queda sin memoria, la terminal sigue viva) y deja su rastro en `entrenos/`: la orden, los eventos (`progreso.jsonl`) y la salida del script. Solo hay un trabajo a la vez. Ojo con la memoria de la GPU: el servidor tiene su cerebro cargado mientras se entrena, y en una tarjeta de 6 GB caben los dos, pero con poco margen.

## Datos

```bash
python -m entrenamiento.generar_datos
```

Escribe en `entrenamiento/datos/` situaciones del zombi del parking y de la puerta norte, etiquetadas por reglas:

| Fichero | Para qué | Frases |
| --- | --- | --- |
| `entrenamiento.jsonl` | entrenar la LoRA (800) | mitad A |
| `validacion.jsonl` | elegir la mejor época de la LoRA (300) | mitad A |
| `calibracion.jsonl` | ajustar temperaturas (300) | mitad B, nunca vistas al entrenar |
| `prueba.jsonl` | medir (300), situaciones distintas de las de calibración | mitad B |
| `articulo.jsonl` | las variantes de los ejemplos del artículo, etiquetadas a mano | las del artículo |

Calibrar con las frases de entrenamiento es un error: la LoRA las acierta casi todas y la calibración concluye que puede estar aún más segura, justo lo contrario de lo que pasa luego con frases nuevas.

Cada línea es una situación con sus preguntas (las mismas de `ejemplos/`) y las respuestas correctas:

```json
{"state": {...}, "questions": {...}, "respuestas": {"accion": "atacar", "hambre": 2, "humano_cerca": true}}
```

`choice` se etiqueta con el nombre de la opción, `score` con el nivel y `noul` con `true`/`false`. Puedes añadir tus propias situaciones con el mismo formato.

## 1. Calibrar

```bash
python -m entrenamiento.calibrar                     # CPU; --dispositivo cuda si quieres
python -m entrenamiento.evaluar --calibracion calibracion/multilingual.json
LAYA_CALIBRACION=calibracion/multilingual.json ./run.sh
```

Debe bajar el ECE (la distancia entre lo seguro que dice estar y lo que acierta). Los aciertos no cambian.

## 2. LoRA

```bash
python -m entrenamiento.lora                         # GPU si hay
python -m entrenamiento.calibrar --modelo modelos/lora-refugio
python -m entrenamiento.evaluar --modelo modelos/lora-refugio --calibracion calibracion/lora-refugio.json
LAYA_MODELO_MULTILINGUAL=modelos/lora-refugio LAYA_CALIBRACION=calibracion/lora-refugio.json ./run.sh
```

Opciones útiles: `--max-casos 40 --epocas 1` para un ensayo rápido, `--dispositivo cpu`, `--rango 16`, `--checkpointing` si falta memoria y `--sin-barajar` para comparar con lo que pasa si no se barajan las opciones.

Al entrenar se barajan las opciones de cada `choice`, para atacar el sesgo de orden. `evaluar.py` mide cuántas respuestas cambian al invertir el orden.

En `modelos/lora-refugio/` queda un checkpoint completo de Laya (se carga con `laya.Agent("modelos/lora-refugio")`), el adaptador suelto (`lora.safetensors`, unos MB) y `lora.json` con la configuración y el historial. Las capas con LoRA se guardan en fp32 para que el redondeo a fp16 no se coma el ajuste.

## Advertencias

- Los datos son sintéticos: si la LoRA saca un 99 %, lo que ha aprendido son mis reglas, no el apocalipsis. La prueba usa otras frases para que al menos no sea memoria pura.
- `comun.py` usa métodos privados de `laya.Agent` (`_encode_state` y compañía), probados con laya 0.3.20.
