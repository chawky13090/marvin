@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Marvin - Installation du paquet Windows
pushd "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-marvin-package.ps1" %*
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="3010" (
    echo.
    echo [REDEMARRAGE REQUIS] Installation conservee. Elle reprendra a la prochaine ouverture de session.
    popd
    exit /b 3010
)
if not "%RESULT%"=="0" (
    echo.
    echo [ERREUR] Installation interrompue. Le detail est affiche ci-dessus.
    pause
)
popd
exit /b %RESULT%
