@echo off
chcp 65001 >nul
setlocal
pushd "%~dp0"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0scripts\restart-marvin.ps1" %*
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
