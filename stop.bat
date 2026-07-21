@echo off
chcp 65001 >nul
setlocal
pushd "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\stop-marvin.ps1" %*
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
