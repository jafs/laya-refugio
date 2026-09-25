# Crea .venv e instala las dependencias. Por defecto torch en versión CPU; para GPU NVIDIA:
#   $env:TORCH_VARIANT = "cu126"; .\setup.ps1   (también cu130, cu132)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$TorchVersion = "2.14.0"

# Usa $env:PYTHON si está definido; si no, el primero de py -3, python3 o python que sea 3.10+.
$Python = $env:PYTHON
if (-not $Python) {
    foreach ($candidato in @("py -3", "python3", "python")) {
        $partes = $candidato.Split(" ")
        try {
            & $partes[0] $partes[1..($partes.Length - 1)] -c "import sys; sys.exit(sys.version_info < (3, 10))" 2>$null
            if ($LASTEXITCODE -eq 0) { $Python = $candidato; break }
        } catch {}
    }
}
if (-not $Python) {
    Write-Error "No se encontró Python 3.10+ (probados: py -3, python3, python). Define `$env:PYTHON."
}

$partes = $Python.Split(" ")
& $partes[0] $partes[1..($partes.Length - 1)] -m venv .venv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

& $VenvPython -m pip install --upgrade pip
$Variant = if ($env:TORCH_VARIANT) { $env:TORCH_VARIANT } else { "cpu" }
& $VenvPython -m pip install --index-url "https://download.pytorch.org/whl/$Variant" "torch==$TorchVersion+$Variant"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $VenvPython -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Listo. Arranca con: .\run.ps1"
