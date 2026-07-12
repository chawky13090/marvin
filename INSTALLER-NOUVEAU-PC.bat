@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Marvin (SecretaryAI) - Installation sur un nouveau PC
color 0B
pushd "%~dp0"

echo.
echo  ==============================================================
echo     Marvin / SecretaryAI - Installation sur ce PC
echo  ==============================================================
echo.
echo  Ce script installe TOUT le necessaire :
echo    - Python (backend) + dependances
echo    - Node.js (frontend) + dependances
echo    - Ollama + modeles IA (qwen2.5:7b, llava-phi3)
echo.
echo  ATTENTION : il recree les environnements (.venv, .next) car
echo  ceux copies de l'autre PC contiennent des chemins invalides.
echo.
pause
echo.

:: v2.176 -- winget est absent par defaut sur beaucoup d'installations Windows Server
:: (contrairement a Windows 10/11 client) : ne plus en dependre aveuglement. Detecte
:: sa presence UNE fois ; s'il manque, Node et Ollama basculent sur un telechargement
:: direct + installation silencieuse (URL resolue dynamiquement pour Node -- jamais de
:: numero de version fige en dur qui deviendrait faux avec le temps). Python n'a pas
:: d'equivalent JSON officiel simple a interroger en script -- repli sur l'ouverture
:: de la page de telechargement officielle plutot que de deviner une URL de version.
where winget >nul 2>&1
if errorlevel 1 ( set "HAS_WINGET=0" ) else ( set "HAS_WINGET=1" )

:: ============================================================ [1/8] Python
echo [1/8] Verification de Python...
where python >nul 2>&1
if errorlevel 1 (
    if "!HAS_WINGET!"=="1" (
        echo   [!] Python introuvable. Installation via winget...
        winget install -e --id Python.Python.3.13 --accept-package-agreements --accept-source-agreements
    ) else (
        echo   [!] Python introuvable et winget absent ^(frequent sur Windows Server^).
        echo   Ouverture de la page de telechargement officielle dans le navigateur...
        start "" "https://www.python.org/downloads/windows/"
        echo   -^> Telechargez la version stable la plus recente, lancez l'installeur,
        echo      et cochez IMPERATIVEMENT "Add python.exe to PATH".
    )
    echo.
    echo   [IMPORTANT] Une fois Python installe ^(ou apres le winget ci-dessus^) :
    echo   FERMEZ cette fenetre et RELANCEZ ce script ^(le PATH doit etre recharge^).
    popd & pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo   [OK] %%v
echo.

:: ============================================================ [2/8] Node.js
echo [2/8] Verification de Node.js...
where node >nul 2>&1
if errorlevel 1 (
    if "!HAS_WINGET!"=="1" (
        echo   [!] Node.js introuvable. Installation via winget...
        winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
    ) else (
        echo   [!] Node.js introuvable et winget absent. Telechargement direct
        echo   de la derniere version LTS ^(resolue en direct, jamais figee en dur^)...
        set "NODE_MSI=%TEMP%\node-installer.msi"
        :: v2.181 -- ecrit dans un VRAI fichier .ps1 plutot qu'une ligne -Command avec des
        :: guillemets echappes imbriques (\"..\") : ce motif fait planter net le parseur de
        :: cmd.exe sur certaines installations Windows Server (constate en reel -- la fenetre
        :: se fermait sans message des cette ligne). Ecrire le script dans un fichier evite
        :: totalement ce piege de quoting cmd.exe/PowerShell.
        set "NODE_PS1=%TEMP%\marvin_node_lts.ps1"
        > "!NODE_PS1!" echo $idx = Invoke-RestMethod -Uri 'https://nodejs.org/dist/index.json'
        >>"!NODE_PS1!" echo $lts = $idx ^| Where-Object { $_.lts -ne $false } ^| Select-Object -First 1
        >>"!NODE_PS1!" echo $ver = $lts.version
        >>"!NODE_PS1!" echo $url = 'https://nodejs.org/dist/' + $ver + '/node-' + $ver + '-x64.msi'
        >>"!NODE_PS1!" echo Write-Host ^('   Version LTS detectee : ' + $ver^)
        >>"!NODE_PS1!" echo Invoke-WebRequest -Uri $url -OutFile '!NODE_MSI!' -UseBasicParsing
        powershell -NoProfile -ExecutionPolicy Bypass -File "!NODE_PS1!"
        set "NODE_PS1_RC=!ERRORLEVEL!"
        del "!NODE_PS1!" >nul 2>&1
        if not "!NODE_PS1_RC!"=="0" (
            echo   [ERREUR] Telechargement automatique echoue. Installez manuellement : https://nodejs.org  ^(version LTS^)
            popd & pause & exit /b 1
        )
        echo   Installation silencieuse...
        msiexec /i "!NODE_MSI!" /quiet /norestart
        del "!NODE_MSI!" >nul 2>&1
    )
    echo.
    echo   [IMPORTANT] Node.js vient d'etre installe.
    echo   FERMEZ cette fenetre et RELANCEZ ce script.
    popd & pause & exit /b 1
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do echo   [OK] Node %%v
echo.

:: ============================================================ [3/8] Ollama
echo [3/8] Verification d'Ollama...
set "OLLAMA=ollama"
where ollama >nul 2>&1
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
        set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
        echo   [OK] Ollama trouve dans LOCALAPPDATA.
    ) else if "!HAS_WINGET!"=="1" (
        echo   [!] Ollama introuvable. Installation via winget...
        winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
        set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    ) else (
        echo   [!] Ollama introuvable et winget absent. Telechargement direct...
        set "OLLAMA_EXE=%TEMP%\OllamaSetup.exe"
        powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile '!OLLAMA_EXE!' -UseBasicParsing } catch { exit 1 }"
        if errorlevel 1 (
            echo   [ERREUR] Telechargement echoue. Installez manuellement : https://ollama.com/download
            popd & pause & exit /b 1
        )
        echo   Installation silencieuse...
        "!OLLAMA_EXE!" /VERYSILENT /SUPPRESSMSGBOXES
        del "!OLLAMA_EXE!" >nul 2>&1
        set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    )
) else (
    echo   [OK] Ollama detecte dans le PATH.
)
echo.

:: ============================================================ [4/9] Docker (optionnel - recherche web SearXNG)
echo [4/9] Verification de Docker ^(optionnel - recherche web auto-hebergee^)...
where docker >nul 2>&1
if errorlevel 1 (
    echo   [INFO] Docker non detecte - optionnel, uniquement pour la recherche web
    echo   auto-hebergee ^(SearXNG, evite les blocages anti-bot DuckDuckGo^).
    echo   Installable plus tard : winget install -e --id Docker.DockerDesktop
    echo   Une fois installe, start.bat le configure tout seul ^(rien d'autre a faire^).
) else (
    echo   [OK] Docker detecte - start.bat configurera SearXNG automatiquement.
)
echo.

:: ============================================================ [5/9] Nettoyage
echo [5/9] Nettoyage des environnements copies de l'autre PC...
if exist "backend\.venv" ( rmdir /s /q "backend\.venv" & echo   - backend\.venv supprime )
if exist ".next" ( rmdir /s /q ".next" & echo   - .next supprime )
:: node_modules contient des binaires NATIFS (better-sqlite3) compiles pour le Node
:: de l'AUTRE PC -> on le supprime pour forcer npm a recuperer les bons binaires.
if exist "node_modules" ( rmdir /s /q "node_modules" & echo   - node_modules supprime )
echo   [OK] Pret pour une installation propre.
echo.

:: ============================================================ [6/9] Backend Python
echo [6/9] Creation de l'environnement Python et installation des dependances...
echo   ^(cela peut prendre quelques minutes^)
pushd backend
python -m venv .venv
if errorlevel 1 ( echo   [ERREUR] Creation du venv impossible. & popd & popd & pause & exit /b 1 )
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 ( echo   [ERREUR] Installation des dependances Python echouee. & popd & popd & pause & exit /b 1 )
:: Post-install pywin32 (presse-papiers, fenetres, notifications)
.venv\Scripts\python .venv\Scripts\pywin32_postinstall.py -install >nul 2>&1
popd
echo   [OK] Backend Python pret.
echo.

:: ============================================================ [7/9] Frontend Node
echo [7/9] Installation des dependances du frontend ^(npm install^)...
call npm install
if errorlevel 1 ( echo   [ERREUR] npm install a echoue. & popd & pause & exit /b 1 )
echo   [OK] Frontend pret.
echo.

:: --- Verification des modules natifs (better-sqlite3, sharp) compiles pour CE PC ---
echo   Verification des modules natifs Node...
node -e "require('better-sqlite3'); require('sharp');" >nul 2>&1
if errorlevel 1 (
    echo   [ATTENTION] Un module natif n'a pas pu se charger. Correction automatique...
    call npm rebuild better-sqlite3 sharp
)
node -e "require('better-sqlite3'); require('sharp'); console.log('   [OK] better-sqlite3 + sharp charges.');" 2>nul || echo   [ERREUR] Modules natifs toujours KO -^> supprimez node_modules puis relancez ce script.
:: --- Verification que le backend Python importe ---
pushd backend
.venv\Scripts\python -c "import tools, main" >nul 2>&1 && (echo   [OK] Backend Python importe correctement.) || (echo   [ATTENTION] Le backend Python n'importe pas - verifiez requirements.txt.)
popd
echo.

:: ============================================================ [8/9] Modeles IA
echo [8/9] Telechargement des modeles IA via Ollama ^(le plus long^)...
echo   Demarrage du service Ollama...
start "" /B "!OLLAMA!" serve >nul 2>&1
timeout /t 4 /nobreak >nul
echo   - qwen2.5:7b ^(cerveau principal, ~4.7 Go^)...
"!OLLAMA!" pull qwen2.5:7b
echo   - llava-phi3 ^(vision / OCR, ~2.9 Go^)...
"!OLLAMA!" pull llava-phi3
echo   [INFO] PC peu puissant ? Modele plus leger : "!OLLAMA!" pull qwen2.5:3b
echo.

:: ============================================================ [9/9] Config
echo [9/9] Configuration...
if not exist ".env.local" if exist ".env.local.example" (
    copy ".env.local.example" ".env.local" >nul
    echo   [OK] .env.local cree ^(modifiez-le pour vos comptes Google/Outlook si besoin^).
)
echo.

echo  ==============================================================
echo     INSTALLATION TERMINEE !
echo  ==============================================================
echo.
echo   Pour lancer Marvin :
echo     -^> Double-cliquez sur  start.bat
echo.
echo   Puis ouvrez votre navigateur sur :
echo     -^> http://localhost:3000
echo.
echo   Verifier que tout va bien ^(apres lancement^) :
echo     -^> http://localhost:8005/api/health   ^(doit afficher version + 231 outils^)
echo.
echo   [Optionnel] Generation video IA locale ^(GPU NVIDIA, ~3-5 Go^) :
echo     voir backend\requirements-video.txt
echo.
popd
pause
