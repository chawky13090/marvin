@echo off
chcp 65001 >nul
title SecretaryAI
echo.
echo  ====================================
echo    SecretaryAI - Demarrage en cours
echo  ====================================
echo.

:: Verifier si Ollama tourne deja
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul
if %ERRORLEVEL% NEQ 0 (
    echo [1/3] Demarrage d'Ollama en arriere-plan...
    start "" /B ollama serve
    timeout /t 3 /nobreak >nul
    echo       Ollama demarre.
) else (
    echo [1/3] Ollama tourne deja.
)

:: Verifier si le backend Python tourne deja (port 8005)
netstat -an 2>nul | find ":8005" | find "LISTENING" >nul
if %ERRORLEVEL% NEQ 0 (
    echo [2/3] Demarrage du backend Python...
    start "SecretaryAI - Backend" /D "%~dp0backend" cmd /c "start.bat"
    timeout /t 4 /nobreak >nul
    echo       Backend demarre sur http://localhost:8005
) else (
    echo [2/3] Backend Python tourne deja sur le port 8005.
)

echo [3/3] Demarrage du frontend Next.js...
echo.
echo  Frontend : http://localhost:3000
echo  Backend  : http://localhost:8005
echo  API docs : http://localhost:8005/docs
echo.
echo  Appuyez sur Ctrl+C pour arreter le frontend.
echo  Fermez la fenetre "Backend" separement si besoin.
echo.

npm run dev

pause
