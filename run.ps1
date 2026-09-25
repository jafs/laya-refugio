# Arranca la terminal del refugio en http://localhost:8000 ($env:PORT = 9000 para cambiarlo).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Port = if ($env:PORT) { $env:PORT } else { "8000" }
& (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") -m uvicorn app.main:app --host 127.0.0.1 --port $Port --timeout-graceful-shutdown 3
