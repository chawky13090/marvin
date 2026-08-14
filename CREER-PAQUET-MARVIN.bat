@echo off
setlocal EnableExtensions
chcp 65001 >nul
pushd "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-marvin-windows-package.ps1" %*
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="0" (
    echo.
    echo [OK] Le paquet Windows est disponible dans le dossier dist.
)
if not "%RESULT%"=="0" pause
popd
exit /b %RESULT%
