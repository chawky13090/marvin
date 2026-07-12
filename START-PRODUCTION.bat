@echo off
chcp 65001 >nul
title Marvin - Production
pushd "%~dp0"

echo.
echo  ====================================
echo    Marvin - Demarrage (PRODUCTION)
echo  ====================================
echo.
echo  Different de start.bat : le frontend tourne en mode PRODUCTION
echo  (next build + next start), pas en mode developpement (next dev).
echo  Plus rapide, plus stable pour un serveur laisse sans surveillance.
echo.

:: v2.176 -- construit le frontend UNE fois (ou si le build n'existe pas encore /
:: a ete supprime) ; les demarrages suivants reutilisent le build deja pret et
:: sont quasi instantanes. Pour reconstruire apres une mise a jour du code,
:: supprimez le dossier .next ou relancez ce script avec l'argument "rebuild".
if "%~1"=="rebuild" if exist ".next" (
    echo [0/4] Argument "rebuild" -^> suppression du build existant...
    rmdir /s /q ".next"
)
if not exist ".next\BUILD_ID" (
    echo [0/4] Construction du frontend ^(npm run build^)... ^(peut prendre 1-3 min^)
    call npm run build
    if errorlevel 1 (
        echo   [ERREUR] La construction a echoue -- voir le message ci-dessus.
        popd & pause & exit /b 1
    )
    echo   [OK] Build de production pret.
) else (
    echo [0/4] Build de production deja present ^(relancez avec "rebuild" apres une mise a jour du code^).
)
echo.

:: Verifier si Ollama tourne deja
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul
if %ERRORLEVEL% NEQ 0 (
    echo [1/4] Demarrage d'Ollama en arriere-plan...
    start "" /B ollama serve
    timeout /t 3 /nobreak >nul
    echo       Ollama demarre.
) else (
    echo [1/4] Ollama tourne deja.
)

:: Verifier si le backend Python tourne deja (port 8005)
netstat -an 2>nul | find ":8005" | find "LISTENING" >nul
if %ERRORLEVEL% NEQ 0 (
    echo [2/4] Demarrage du backend Python...
    start "SecretaryAI - Backend" /D "%~dp0backend" cmd /c "start.bat"
    timeout /t 4 /nobreak >nul
    echo       Backend demarre sur http://localhost:8005
) else (
    echo [2/4] Backend Python tourne deja sur le port 8005.
)

:: Recherche web auto-hebergee (SearXNG) - entierement optionnelle, meme logique que start.bat
where docker >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [3/4] Recherche web auto-hebergee ^(SearXNG^) en arriere-plan...
    start "SecretaryAI - SearXNG" /MIN powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0docker\searxng\start-searxng.ps1"
) else (
    echo [3/4] Docker non detecte - recherche web via DuckDuckGo ^(voir docker\searxng pour l'ameliorer^)
)

echo [4/4] Demarrage du frontend Next.js ^(mode production^)...
echo.
echo  Frontend : http://localhost:3000  ^(accessible aussi via l'IP du serveur sur le reseau^)
echo  Backend  : http://localhost:8005
echo  API docs : http://localhost:8005/docs
echo.
echo  Appuyez sur Ctrl+C pour arreter le frontend.
echo  Fermez la fenetre "Backend" separement si besoin.
echo.

call npm run start

popd
pause
