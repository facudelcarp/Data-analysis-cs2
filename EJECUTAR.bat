@echo off
chcp 65001 >nul
title CS2 Data Analysis
cls

echo ===================================================================
echo                     CS2 DATA ANALYSIS
echo            Iniciando la plataforma de analitica CS2...
echo ===================================================================
echo.

cd /d "%~dp0"

set "VENV_PYTHON=%~dp0venv\Scripts\python.exe"

:: 1. Verificar si existe el entorno virtual con Python
if not exist "%VENV_PYTHON%" (
    echo [!] No se encontro el entorno virtual en "%~dp0venv".
    echo [*] Configurando el entorno e instalando librerias automaticamente...
    echo     Esto puede tardar un par de minutos en la primera ejecucion.
    echo.

    where py >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        py -3 -m venv venv
    ) else (
        where python >nul 2>nul
        if %ERRORLEVEL% equ 0 (
            python -m venv venv
        ) else (
            echo [ERROR] No se encontro Python instalado en el sistema.
            echo Por favor instala Python desde https://www.python.org/
            echo.
            pause
            exit /b 1
        )
    )

    if not exist "%VENV_PYTHON%" (
        echo [ERROR] Fallo al crear el entorno virtual.
        pause
        exit /b 1
    )

    echo [*] Instalando dependencias necesarias...
    "%VENV_PYTHON%" -m pip install --upgrade pip
    "%VENV_PYTHON%" -m pip install -r requirements.txt
    "%VENV_PYTHON%" -m pip install -e .
    echo.
    echo [*] Instalacion completada con exito.
    echo.
)

:: 2. Lanzar la aplicacion (ventana nativa, sin consola)
echo [*] Abriendo CS2 Data Analysis...
"%VENV_PYTHON%" -c "import PySide6, pyqtgraph" 2>nul || (
    echo [*] Actualizando dependencias de la interfaz nativa...
    "%VENV_PYTHON%" -m pip install -r requirements.txt
    "%VENV_PYTHON%" -m pip install -e .
)
if not "%~1"=="" (
    start "" "%~dp0venv\Scripts\pythonw.exe" -m cs2analysis.desktop "%~1"
) else (
    start "" "%~dp0venv\Scripts\pythonw.exe" -m cs2analysis.desktop
)
