# Arranca la terminal del refugio en http://localhost:8000 ($env:PORT = 9000 para cambiarlo).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Variables de .env, si existe. Las que ya estén definidas en el entorno tienen prioridad.
if (Test-Path .env) {
    foreach ($linea in Get-Content .env -Encoding utf8) {
        $linea = $linea.Trim()
        if (-not $linea -or $linea.StartsWith("#") -or -not $linea.Contains("=")) { continue }
        $clave, $valor = $linea.Split("=", 2)
        $clave = $clave.Trim()
        if (-not [Environment]::GetEnvironmentVariable($clave)) {
            Set-Item -Path "env:$clave" -Value $valor.Trim().Trim('"')
        }
    }
}

$Port = if ($env:PORT) { $env:PORT } else { "8000" }
& (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") -m uvicorn app.main:app --host 127.0.0.1 --port $Port --timeout-graceful-shutdown 3
