@echo off
setlocal EnableExtensions
chcp 65001 >nul
pushd "%~dp0"
call "%~dp0INSTALLER-MARVIN.bat" %*
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
