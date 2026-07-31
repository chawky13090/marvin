@echo off
chcp 65001 >nul
setlocal
pushd "%~dp0"
echo [INFO] Marvin utilise toujours Turbopack. START-PRODUCTION.bat est conserve
echo        comme alias de compatibilite et appelle le lanceur autoritaire start.bat.
call "%~dp0start.bat"
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
