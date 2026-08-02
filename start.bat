@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
title SecretaryAI
echo.
echo  ====================================
echo    SecretaryAI - Demarrage en cours
echo  ====================================
echo.

:: Sérialise la phase de démarrage pour empêcher deux piles concurrentes.
set "START_LOCK_STATE="
for /f "usebackq delims=" %%L in (`powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0scripts\marvin-startup-lock.ps1" -Action acquire`) do set "START_LOCK_STATE=%%L"
if not "%START_LOCK_STATE%"=="acquired" (
    echo [INFO] Une operation de cycle de vie est en cours. Attente puis reevaluation...
    powershell -NoProfile -NonInteractive -Command "$p='%~dp0runtime\lifecycle\startup.lock';$d=(Get-Date).AddSeconds(120);while((Test-Path -LiteralPath $p)-and(Get-Date)-lt$d){Start-Sleep -Milliseconds 200};if(Test-Path -LiteralPath $p){exit 1}else{exit 0}"
    if errorlevel 1 exit /b 1
    call "%~f0"
    exit /b %ERRORLEVEL%
)

:: Preflight reproductible : executables, venv et modules Node natifs.
echo [0/4] Verification de l'environnement...
where node >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERREUR] Node.js est introuvable. Lancez INSTALLER-NOUVEAU-PC.bat.
    goto :startup_error
)
if not exist "%~dp0backend\.venv\Scripts\python.exe" (
    echo [ERREUR] backend\.venv est absent ou incomplet. Lancez INSTALLER-NOUVEAU-PC.bat.
    goto :startup_error
)
pushd "%~dp0backend"
.venv\Scripts\python.exe -c "import python_runtime; raise SystemExit(0 if python_runtime.inspect_runtime()['portable'] else 2)" >nul 2>&1
set "PYTHON_RUNTIME_RC=%ERRORLEVEL%"
popd
if not "%PYTHON_RUNTIME_RC%"=="0" (
    echo [ERREUR] backend\.venv depend d un Python temporaire, absent ou non supporte.
    echo          Arretez Marvin puis executez :
    echo          powershell -ExecutionPolicy Bypass -File scripts\migrate-python-runtime.ps1 -Action Migrate
    goto :startup_error
)
if not exist "%~dp0node_modules" (
    echo [ERREUR] node_modules est absent. Lancez INSTALLER-NOUVEAU-PC.bat.
    goto :startup_error
)
node -e "require('sharp')" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo       Modules Node natifs incompatibles - reconstruction automatique...
    set "PYTHON=%~dp0backend\.venv\Scripts\python.exe"
    set "npm_config_cache=%~dp0.npm-cache"
    call npm rebuild sharp
    if errorlevel 1 (
        echo [ERREUR] Reconstruction impossible. Lancez INSTALLER-NOUVEAU-PC.bat.
        goto :startup_error
    )
)
node scripts\check_runtime.mjs
if %ERRORLEVEL% NEQ 0 goto :startup_error
echo       Environnement valide.
echo.

:: Resout Ollama meme s'il est installe dans LOCALAPPDATA mais absent du PATH.
:: Priorite au chemin d'installation Windows officiel afin d'eviter les alias
:: incomplets ou les differences de PATH entre un terminal et Start-Process.
set "OLLAMA_EXE="
for /f "usebackq delims=" %%E in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\resolve-ollama-exe.ps1"`) do set "OLLAMA_EXE=%%E"
if not defined OLLAMA_EXE (
    where ollama >nul 2>&1
    if not errorlevel 1 set "OLLAMA_EXE=ollama"
)
if not defined OLLAMA_EXE (
    echo [ERREUR] Ollama est introuvable. Lancez INSTALLER-NOUVEAU-PC.bat.
    goto :startup_error
)

:: Docker/Hyper-V peut exclure dynamiquement le port Ollama historique 11434.
:: Choisir un port local réellement disponible, puis transmettre la même valeur
:: à Ollama, FastAPI et Next.js. Aucune écoute réseau externe n'est ajoutée.
set "OLLAMA_PORT="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\resolve-ollama-port.ps1"`) do set "OLLAMA_PORT=%%P"
if not defined OLLAMA_PORT (
    echo [ERREUR] Aucun port local disponible pour Ollama.
    echo Verifiez les plages TCP exclues avec : netsh interface ipv4 show excludedportrange protocol=tcp
    goto :startup_error
)
set "OLLAMA_HOST=127.0.0.1:%OLLAMA_PORT%"
set "OLLAMA_URL=http://127.0.0.1:%OLLAMA_PORT%"
set "OLLAMA_BASE_URL=http://127.0.0.1:%OLLAMA_PORT%/v1"
set "NEXT_PUBLIC_OLLAMA_PORT=%OLLAMA_PORT%"
:: v2.550 - Fenetre de contexte fixee GLOBALEMENT sur le service (pas par appel Python) :
:: prewarm, professeur et agent partagent alors tous la meme instance chargee (meme cle
:: modele+num_ctx) au lieu de se disputer le defaut 4096 tokens d'Ollama, qui tronquait le
:: prompt systeme et les schemas d'outils avant meme le message de l'utilisateur.
if not defined OLLAMA_CONTEXT_LENGTH set "OLLAMA_CONTEXT_LENGTH=32768"
echo       Ollama demande sur %OLLAMA_HOST% (contexte local minimal %OLLAMA_CONTEXT_LENGTH%).
echo       Doctor verifiera l'allocation reelle; les modeles Cloud gardent leur contexte maximal.

:: Verifier le service par HTTP : tasklist peut masquer un processus lance avec un autre
:: niveau de privileges alors que l'API Ollama fonctionne parfaitement.
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing ($env:OLLAMA_URL + '/api/tags') -TimeoutSec 3; if($r.StatusCode -eq 200){exit 0}; exit 1 } catch { exit 1 }" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [1/4] Demarrage d'Ollama en arriere-plan...
    start "" /B "%OLLAMA_EXE%" serve
    powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 30;$i++){try{$r=Invoke-WebRequest -UseBasicParsing ($env:OLLAMA_URL + '/api/tags') -TimeoutSec 2;if($r.StatusCode -eq 200){$ok=$true;break}}catch{};Start-Sleep -Milliseconds 500};if(-not $ok){exit 1}" >nul 2>&1
    if errorlevel 1 (
        echo [ERREUR] Ollama ne repond pas sur le port %OLLAMA_PORT%.
        goto :startup_error
    )
    echo       Ollama demarre.
) else (
    echo [1/4] Ollama tourne deja.
)

:: Verifier l'identite HTTP du backend, pas uniquement l'occupation du port.
powershell -NoProfile -Command "try{$d=Invoke-RestMethod 'http://127.0.0.1:8005/api/health' -TimeoutSec 3;if($d.status -eq 'ok' -and $d.backend -eq 'python-fastapi'){exit 0};exit 1}catch{exit 1}" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [2/4] Demarrage du backend Python...
    start "SecretaryAI - Backend" /D "%~dp0backend" cmd /c "start.bat"
    powershell -NoProfile -Command "$ok=$false;for($i=0;$i -lt 120;$i++){try{$d=Invoke-RestMethod 'http://127.0.0.1:8005/api/health' -TimeoutSec 2;if($d.status -eq 'ok' -and $d.backend -eq 'python-fastapi'){$ok=$true;break}}catch{};Start-Sleep -Milliseconds 500};if(-not $ok){exit 1}" >nul 2>&1
    if errorlevel 1 (
        echo [ERREUR] Le backend ne repond pas sur le port 8005.
        echo Verifiez qu'aucune autre application n'utilise ce port.
        goto :startup_error
    )
    echo       Backend pret sur http://localhost:8005
) else (
    echo [2/4] Backend Python tourne deja sur le port 8005.
)

:: Recherche web auto-hebergee (SearXNG) - entierement optionnelle et dynamique :
:: ignoree silencieusement si Docker n'est pas installe (Marvin retombe sur
:: DuckDuckGo/autres providers configures). Idempotent (reglages/conteneur deja
:: prets = redemarrage quasi instantane) - lancee dans sa propre fenetre pour ne
:: jamais bloquer le demarrage du reste (Docker Desktop peut prendre 1-2 min).
where docker >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [3/4] Recherche web auto-hebergee ^(SearXNG^) en arriere-plan...
    start "SecretaryAI - SearXNG" /MIN powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0docker\searxng\start-searxng.ps1"
) else (
    echo [3/4] Docker non detecte - capacite SearXNG indisponible, socle Marvin maintenu.
)

echo [4/4] Demarrage du frontend Next.js...
echo.
echo  Frontend : http://localhost:3000
echo  Backend  : http://localhost:8005
echo  API docs : http://localhost:8005/docs
if exist "%~dp0runtime\https\caddy.exe" (
    for /f "usebackq delims=" %%H in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\ensure-marvin-https.ps1" 2^>nul`) do set "MARVIN_HTTPS_URL=%%H"
    if defined MARVIN_HTTPS_URL (
        echo  HTTPS    : !MARVIN_HTTPS_URL!
    ) else (
        echo  HTTPS    : indisponible ^(socle local maintenu^)
    )
)
echo.
echo  Appuyez sur Ctrl+C pour arreter le frontend.
echo  Pour tout arreter proprement : stop.bat
echo.

powershell -NoProfile -Command "try{$d=Invoke-RestMethod 'http://127.0.0.1:3000/api/status' -TimeoutSec 3;if($null -ne $d.ollama -and $null -ne $d.integrations){exit 0};exit 1}catch{exit 1}" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  Frontend deja actif sur http://localhost:3000
    call :release_start_lock
    exit /b 0
)
powershell -NoProfile -Command "$c=Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue; if($null -eq $c){exit 1}; foreach($x in @($c)){ $p=Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $x.OwningProcess) -ErrorAction SilentlyContinue; $i=('{0} {1}' -f $p.ExecutablePath,$p.CommandLine); if($i.IndexOf('%~dp0',[StringComparison]::OrdinalIgnoreCase) -ge 0 -and $i -match '(?i)next|start_next_dev'){exit 0} }; exit 1" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  Frontend Marvin deja en ecoute; conservation du processus existant.
    call :release_start_lock
    exit /b 0
)
powershell -NoProfile -Command "$c=Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue; if($null -ne $c){exit 0}; exit 1" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [ERREUR] Le port 3000 est occupe par une application qui n'est pas Marvin.
    goto :startup_error
)

call :release_start_lock
for /f "usebackq delims=" %%S in (`powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0scripts\marvin-startup-lock.ps1" -Action stop-requested`) do set "STOP_REQUESTED=%%S"
if "%STOP_REQUESTED%"=="true" exit /b 0
call npm run dev
exit /b %ERRORLEVEL%

:release_start_lock
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0scripts\marvin-startup-lock.ps1" -Action release >nul 2>&1
exit /b 0

:startup_error
call :release_start_lock
pause
exit /b 1
