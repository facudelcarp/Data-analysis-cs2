@echo off
chcp 65001 >nul
:: App nativa (en migración). Usa el mismo entorno que EJECUTAR.bat: correlo una vez antes si no existe "venv".
cd /d "%~dp0"
set "VENV_PYTHON=%~dp0venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    echo [!] No existe el entorno. Ejecuta primero EJECUTAR.bat para instalarlo.
    pause
    exit /b 1
)
"%VENV_PYTHON%" -c "import PySide6, pyqtgraph" 2>nul || (
    echo [*] Instalando la interfaz nativa (PySide6, pyqtgraph^)...
    "%VENV_PYTHON%" -m pip install -r requirements.txt
)
start "" "%~dp0venv\Scripts\pythonw.exe" -m cs2analysis.desktop %*
