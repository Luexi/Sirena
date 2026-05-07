@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD=py -3.11"
set "VENV_PY=.venv\Scripts\python.exe"
set "VENV_PIP=.venv\Scripts\pip.exe"
set "LOCAL_GPU_DIR=%CD%\.local_gpu_libs"

if exist "%LOCAL_GPU_DIR%" (
    set "PATH=%LOCAL_GPU_DIR%;%PATH%"
)

where py >nul 2>nul
if errorlevel 1 (
    echo No se encontro el launcher py de Python.
    exit /b 1
)

if not exist "%VENV_PY%" (
    echo Creando entorno virtual con Python 3.11...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 exit /b 1
)

echo Actualizando pip...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

echo Instalando dependencias...
"%VENV_PIP%" install -r requirements.txt
if errorlevel 1 exit /b 1

echo Ejecutando pipeline...
"%VENV_PY%" pipeline_transcripcion.py %*
exit /b %errorlevel%
