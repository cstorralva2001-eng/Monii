$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    $pythonCandidates = @()
    if ($env:MONII_PYTHON) { $pythonCandidates += $env:MONII_PYTHON }
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) { $pythonCandidates += $pythonCommand.Source }
    $pythonCandidates += Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $moniiPython = $null
    foreach ($candidate in $pythonCandidates) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        try {
            & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { $moniiPython = $candidate; break }
        } catch { continue }
    }
    if (-not $moniiPython) {
        throw 'Instala Python 3.12 o superior desde python.org y vuelve a ejecutar este archivo.'
    }
    & $moniiPython -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno. Revisa tu instalación de Python.' }
}
& '.\.venv\Scripts\python.exe' -c 'import streamlit, pandas, openpyxl, psycopg, authlib' 2>$null
if ($LASTEXITCODE -ne 0) {
    & '.\.venv\Scripts\python.exe' -m pip install --no-cache-dir -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias. Revisa tu conexión y vuelve a ejecutar iniciar.ps1.' }
}
& '.\.venv\Scripts\python.exe' -m streamlit run app.py
