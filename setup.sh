#!/usr/bin/env bash
# Crea .venv e instala las dependencias. Por defecto torch en versión CPU; para GPU NVIDIA:
#   TORCH_VARIANT=cu126 ./setup.sh   (también cu130, cu132)
set -euo pipefail
cd "$(dirname "$0")"

TORCH_VERSION=2.14.0

# Usa $PYTHON si está definido; si no, el primero de python3/python que sea 3.10 o superior
# (en Windows python3 suele ser el alias de la Microsoft Store, que no arranca).
if [ -z "${PYTHON:-}" ]; then
  for candidato in python3 python; do
    if "$candidato" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
      PYTHON="$candidato"
      break
    fi
  done
fi
if [ -z "${PYTHON:-}" ]; then
  echo "No se encontró Python 3.10+ (probados: python3, python). Define PYTHON=/ruta/a/python." >&2
  exit 1
fi

"$PYTHON" -m venv .venv
if [ -d .venv/Scripts ]; then VENV_BIN=.venv/Scripts; else VENV_BIN=.venv/bin; fi

"$VENV_BIN/python" -m pip install --upgrade pip
# La etiqueta local (+cpu, +cu126...) obliga a pip a cambiar de variante al volver a ejecutarlo;
# en macOS las ruedas CPU no la llevan.
TORCH_VARIANT="${TORCH_VARIANT:-cpu}"
TORCH_SPEC="torch==$TORCH_VERSION+$TORCH_VARIANT"
if [ "$TORCH_VARIANT" = cpu ] && [ "$(uname -s)" = Darwin ]; then TORCH_SPEC="torch==$TORCH_VERSION"; fi
"$VENV_BIN/python" -m pip install --index-url "https://download.pytorch.org/whl/$TORCH_VARIANT" "$TORCH_SPEC"
"$VENV_BIN/python" -m pip install -r requirements-dev.txt

echo
echo "Listo. Arranca con: ./run.sh"
