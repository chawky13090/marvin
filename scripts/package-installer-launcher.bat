@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Marvin - Installation du paquet Windows
pushd "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-marvin-package.ps1" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo.
    echo [ERREUR] Installation interrompue. Le detail est affiche ci-dessus.
    pause
)
popd
exit /b %RESULT%
