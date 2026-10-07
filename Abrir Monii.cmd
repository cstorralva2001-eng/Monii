@echo off
setlocal
cd /d "%~dp0"
set "MONII_LAUNCH_PYTHON=%~dp0.venv\Scripts\python.exe"
if exist "%MONII_LAUNCH_PYTHON%" goto launch
set "MONII_LAUNCH_PYTHON=%~dp0..\..\.venv\Scripts\python.exe"
if exist "%MONII_LAUNCH_PYTHON%" goto launch
echo Primero instala Monii siguiendo README.md o ejecutando iniciar.ps1.
pause
exit /b 1
:launch
"%MONII_LAUNCH_PYTHON%" "%~dp0abrir.py"
if errorlevel 1 pause
