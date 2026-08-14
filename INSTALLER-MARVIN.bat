@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Marvin - Installation Windows en un clic
pushd "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-marvin-oneclick.ps1" %*
set "RESULT=%ERRORLEVEL%"

if not "%RESULT%"=="0" (
    echo.
    echo [ERREUR] L'installation n'est pas terminee. Consultez :
    echo         runtime\install\install.log.jsonl
    echo         runtime\install\state.json
    echo.
    echo Vous pouvez relancer ce meme fichier : les etapes deja validees
    echo seront controlees puis reutilisees.
    pause
)

popd
exit /b %RESULT%
