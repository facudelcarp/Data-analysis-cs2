@echo off
chcp 65001 >nul
title Crear Acceso Directo - CS2 Data Analysis
cls

echo ===================================================================
echo               CS2 Data Analysis - Acceso Directo
echo ===================================================================
echo.

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $d = [Environment]::GetFolderPath('Desktop'); $s = $ws.CreateShortcut(\"$d\CS2 Data Analysis.lnk\"); $s.TargetPath = '%~dp0EJECUTAR.bat'; $s.WorkingDirectory = '%~dp0'; $s.Description = 'Lanzador CS2 Data Analysis'; $s.Save(); Write-Host '[OK] Acceso directo creado en tu Escritorio: CS2 Data Analysis' -ForegroundColor Green;"

echo.
echo ===================================================================
echo Listo. Ya puedes iniciar la app directamente desde tu Escritorio.
echo ===================================================================
echo.
pause
