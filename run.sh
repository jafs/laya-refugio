#!/usr/bin/env bash
# Arranca la terminal del refugio en http://localhost:8000 (PORT=9000 ./run.sh para cambiarlo).
set -euo pipefail
cd "$(dirname "$0")"
# En Windows el venv usa Scripts/ en lugar de bin/.
if [ -d .venv/Scripts ]; then VENV_BIN=.venv/Scripts; else VENV_BIN=.venv/bin; fi
exec "$VENV_BIN/python" -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}" --timeout-graceful-shutdown 3
