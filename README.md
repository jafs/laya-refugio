# Terminal del refugio

Te doy la bienvenida al refugio de la central eléctrica. Aquí podrás jugar con [Laya](https://huggingface.co/convaiinnovations/laya), un modelo de decisión. Sólo tienes que proporcionarle una situación y un puñado de preguntas cerradas, y te devolverá una respuesta de tu lista con su probabilidad.

Este código acompaña al artículo [Modelos de decisión: el cerebro de un zombi](https://jafs.github.io/articles/posts/20260926.html). Todos los ejemplos ocurren en un apocalipsis zombi, y es que no queda otra que decidir si abrimos la puerta norte para dejar entrar a las personas que buscan refugio, o la mantenemos firmemente cerrada.

## Requisitos

Espero que tengas a mano unos cuantos disquetes, porque necesitas:

- Python 3.10 o superior.
- Unos 3 GB de disco (torch y el checkpoint multilingüe) y otros 3 GB de RAM libres.
- GPU NVIDIA opcional. Sin ella funcionará igual, solo que más despacio (del orden de medio segundo por decisión).

## Instalación

Da igual el equipo que estés usando en el refugio, un servidor con Linux, un portátil con macOS o un sobremesa con Git Bash. Con todos ellos simplemente ejecuta:

```bash
./setup.sh                      # torch en versión CPU
TORCH_VARIANT=cu126 ./setup.sh  # torch con CUDA (también cu130, cu132)
```

¿Y si en tu refugio sólo hay Windows? Pues nada como abrir PowerShell y escribir:

```powershell
.\setup.ps1
$env:TORCH_VARIANT = "cu126"; .\setup.ps1
```

Puedes llamar al setup cuantas veces quieras para pasar de CPU a GPU o viceversa.

## Uso

Supongo que ya quieres pasar a la acción, escribe en el terminal:

```bash
./run.sh          # o .\run.ps1 en PowerShell
```

En un navegador ve a <http://localhost:8000>.

La primera vez se descargará el checkpoint multilingüe (unos 650 MB) a la caché de Hugging Face. La terminal te mostrará el progreso mientras tanto. Pero por suerte las siguientes veces puedes apagar la emisora de radio del refugio, ya que se cargará directamente desde la caché.

> **🗒️ Nota en la cabaña** \
> La caché donde se descarga el modelo es la estándar de Hugging Face (`~/.cache/huggingface`) o si tienes una variable de entorno `HF_HOME`, será adonde apunte dicha variable. Si quieres liberar espacio, borra el modelo desde ahí.

La versión del modelo está fijada en `REVISION` (`app/cerebro.py`), la misma con la que se probaron los ejemplos. Si en tu caché hay otra más antigua, se descarga la buena una vez y listo.

## Configuración

Siempre puedes personalizar todo aún más, si escribes un .env con alguna de estas variables:

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `LAYA_CHECKPOINTS` | `multilingual` | Checkpoints que se cargan, separados por comas: `multilingual`, `english`. Con los dos, el `Router` de Laya manda cada texto al que mejor lo entiende (el de inglés ocupa otros 800 MB). |
| `LAYA_DEFAULT` | el primero de la lista | Checkpoint para los textos cuyo idioma no se reconoce. |
| `LAYA_DEVICE` | `auto` | `auto` (CUDA o MPS si hay, si no CPU), `cpu`, `cuda`, `cuda:1`... |
| `LAYA_PRECISION` | `auto` | `auto`, `fp16` o `fp32`. Laya usa fp16 en GPU, pero en las tarjetas que no tienen tensor cores el fp16 va varias veces más lento que el fp32; en modo `auto` se detectan y se usa fp32. |
| `PORT` | `8000` | Puerto HTTP. |

## API

| Método | Ruta | Qué hace |
| --- | --- | --- |
| `GET` | `/api/status` | Estado del cerebro: `comprobando`, `descargando` (con MB), `cargando`, `listo` o `error`. |
| `GET` | `/api/examples` | Los ejemplos de `ejemplos/*.json`. |
| `POST` | `/api/predict` | `{"state": ..., "questions": {...}}` → respuesta de Laya, checkpoint elegido y `latency_ms`. |
| `POST` | `/api/horde` | `{"states": [...], "questions": {...}}` → las mismas preguntas para muchos estados en lotes, con el tiempo comparado contra hacerlo uno a uno. |
| `POST` | `/api/permute` | `{"state": ..., "questions": {...}, "question_id": "accion"}` → repite una pregunta `choice` con las opciones en distinto orden para ver si cambia la respuesta. Spoiler: a veces sí. |

Formato de las preguntas:

```json
{
  "accion": {"type": "choice", "instructions": "¿Qué hace el zombi?",
             "criteria": {"atacar": "hay un humano vivo muy cerca", "vagar": "no hay estímulos"}},
  "hambre": {"type": "score", "instructions": "¿Cuánta hambre tiene?",
             "criteria": ["ninguna", "algo", "mucha"]},
  "humano": {"type": "noul", "instructions": "¿Huele a humano vivo?"}
}
```

## Estructura

```text
app/cerebro.py   descarga única, carga en segundo plano, Router, horda y barajado
app/main.py      FastAPI: endpoints y ficheros estáticos
ejemplos/        situaciones del refugio en JSON
static/          la terminal (HTML + JS, sin compilación)
tests/           tests de la API con un cerebro falso (no cargan el modelo)
```

Tests:

```bash
.venv/bin/python -m pytest      # .venv\Scripts\python -m pytest en Windows
```

## Licencia

[Apache 2.0](LICENSE), la misma que Laya.
