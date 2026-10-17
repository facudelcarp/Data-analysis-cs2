@echo off
chcp 65001 >nul
title CS2 Data Analysis
cls
echo ===================================================================
echo               CS2 Data Analysis - Iniciador Rapido
echo ===================================================================
echo.

cd /d "%~dp0"

if exist "venv\Scripts\activate.bat" (
    echo [*] Activando entorno virtual (venv)...
    call venv\Scripts\activate.bat
    echo [*] Lanzando servidor Streamlit...
    echo [*] Tu navegador se abrira automaticamente en http://localhost:8501
    echo.
    streamlit run app.py
) else (
    echo [!] No se detecto la carpeta venv local.
    echo [*] Intentando ejecutar con Python del sistema...
    python -m streamlit run app.py
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ===================================================================
    echo [ERROR] No se pudo iniciar la aplicacion.
    echo.
    echo Si es la primera vez que la ejecutas, abre PowerShell y corre:
    echo   1. python -m venv venv
    echo   2. .\venv\Scripts\Activate.ps1
    echo   3. pip install -r requirements.txt
    echo   4. pip install -e .
    echo ===================================================================
    echo.
    pause
)
