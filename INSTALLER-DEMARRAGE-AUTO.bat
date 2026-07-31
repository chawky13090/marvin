@echo off
chcp 65001 >nul
setlocal
pushd "%~dp0"
title Marvin - Demarrage automatique

net session >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Executez ce script en tant qu'administrateur.
    popd
    pause
    exit /b 1
)

powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0scripts\install-marvin-autostart.ps1"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo [ERREUR] La configuration du demarrage automatique a echoue.
if "%RESULT%"=="0" echo [OK] Marvin demarrera dans la session interactive du proprietaire.
popd
pause
exit /b %RESULT%
