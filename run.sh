#!/usr/bin/env bash
# Arranca la terminal del refugio en http://localhost:8000 (PORT=9000 ./run.sh para cambiarlo).
set -euo pipefail
cd "$(dirname "$0")"

# Variables de .env, si existe. Las que ya estén definidas en el entorno tienen prioridad.
if [ -f .env ]; then
  while IFS='=' read -r clave valor || [ -n "$clave" ]; do
    clave="${clave//[[:space:]]/}"
    case "$clave" in ''|\#*) continue ;; esac
    valor="${valor%$'\r'}"
    valor="${valor#"${valor%%[![:space:]]*}"}"; valor="${valor%"${valor##*[![:space:]]}"}"
    valor="${valor#\"}"; valor="${valor%\"}"
    if [ -z "${!clave+x}" ]; then export "$clave=$valor"; fi
  done < .env
fi

# En Windows el venv usa Scripts/ en lugar de bin/.
if [ -d .venv/Scripts ]; then VENV_BIN=.venv/Scripts; else VENV_BIN=.venv/bin; fi
exec "$VENV_BIN/python" -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}" --timeout-graceful-shutdown 3
