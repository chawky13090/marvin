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
echo    - Ollama + modeles IA locaux de confidentialite
echo    - LibreOffice pour valider visuellement les documents Word
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

:: ============================================================ [1/9] Python
echo [1/9] Verification de Python...
set "MARVIN_PYTHON="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\resolve-python-runtime.ps1" -Output Path 2^>nul`) do set "MARVIN_PYTHON=%%P"
if not defined MARVIN_PYTHON (
    if "!HAS_WINGET!"=="1" (
        echo   [!] Python introuvable. Installation via winget...
        winget install -e --id Python.Python.3.13 --accept-package-agreements --accept-source-agreements
    ) else (
        echo   [!] Python introuvable et winget absent ^(frequent sur Windows Server^).
        echo   Ouverture de la page de telechargement officielle dans le navigateur...
        start "" "https://www.python.org/downloads/windows/"
        echo   -^> Telechargez Python 3.13 64 bits, lancez l'installeur,
        echo      et cochez IMPERATIVEMENT "Add python.exe to PATH".
    )
    echo.
    echo   [IMPORTANT] Une fois Python installe ^(ou apres le winget ci-dessus^) :
    echo   FERMEZ cette fenetre et RELANCEZ ce script ^(le PATH doit etre recharge^).
    popd & pause & exit /b 1
)
for /f "tokens=*" %%v in ('"!MARVIN_PYTHON!" --version 2^>^&1') do echo   [OK] %%v ^(!MARVIN_PYTHON!^)

:: v2.182 -- certaines installations Python (notamment le paquet officiel sur
:: Windows Server, constate en reel : Python 3.14.6 sans pip) n'embarquent pas
:: pip par defaut. python -m pip --version est en LECTURE SEULE (ne modifie
:: rien) -- seul le repli ensurepip ecrit quelque chose, et seulement si pip
:: est reellement absent.
"!MARVIN_PYTHON!" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo   [ATTENTION] pip introuvable pour cet interpreteur Python. Reparation via ensurepip...
    "!MARVIN_PYTHON!" -m ensurepip --upgrade >nul 2>&1
    "!MARVIN_PYTHON!" -m pip --version >nul 2>&1
    if errorlevel 1 (
        echo   [ERREUR] ensurepip n'a pas pu installer pip. Reinstallez Python depuis
        echo   https://www.python.org/downloads/windows/ en cochant "pip" dans les
        echo   composants optionnels de l'installeur.
        popd & pause & exit /b 1
    )
    echo   [OK] pip reinstalle avec succes.
) else (
    echo   [OK] pip present.
)
echo.

:: ============================================================ [2/9] Node.js
echo [2/9] Verification de Node.js...
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

:: ============================================================ [3/9] Ollama
echo [3/9] Verification d'Ollama...
:: Ollama Desktop Windows peut demarrer avant Marvin. Persister le contexte local
:: AVANT l'installation garantit que les prochains processus Ollama en heritent.
:: Les modeles Ollama Cloud conservent leur contexte maximal gere par le fournisseur.
set "OLLAMA_CONTEXT_LENGTH=32768"
powershell -NoProfile -Command "try { [Environment]::SetEnvironmentVariable('OLLAMA_CONTEXT_LENGTH','32768','User'); exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo   [DEGRADE] Le contexte Ollama local n'a pas pu etre persiste pour cet utilisateur.
    echo   Doctor devra le verifier apres redemarrage d'Ollama.
) else (
    echo   [OK] Contexte Ollama local minimal persiste a 32768 tokens.
)
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

:: ============================================================ [4/9] Docker (Test Forge + recherche web SearXNG)
echo [4/9] Verification de Docker ^(Test Forge et recherche web^)...
where docker >nul 2>&1
if errorlevel 1 (
    echo   [ATTENTION] Docker non detecte. Marvin fonctionnera, mais ne pourra pas
    echo   certifier les scripts et programmes comme prets pour la production.
    echo   Installation recommandee : winget install -e --id Docker.DockerDesktop
    echo   Relancez ensuite ce script pour preparer les conteneurs jetables.
) else (
    docker version --format "{{.Server.Version}}" >nul 2>&1
    if errorlevel 1 (
        echo   [ATTENTION] Docker CLI present mais Docker Desktop ne repond pas.
        echo   Demarrez Docker Desktop puis relancez ce script.
    ) else (
        echo   [OK] Docker Engine disponible.
        powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\prepare-test-forge.ps1"
        if errorlevel 1 (
            echo   [ATTENTION] Preparation Test Forge incomplete.
        ) else (
            echo   [OK] Images Test Forge pretes.
        )
    )
)
echo.

:: ====================================================== [4bis/9] LibreOffice
echo [4bis/9] Validation documentaire LibreOffice...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\manage-libreoffice.ps1" -Action Ensure
if errorlevel 1 (
    echo   [DEGRADE] LibreOffice n a pas pu etre installe ou verifie.
    echo   Marvin reste utilisable, mais la validation visuelle DOCX sera structurelle seulement.
) else (
    echo   [OK] LibreOffice headless disponible pour la validation DOCX.
)
echo.

:: ============================================================ [5/9] Nettoyage
echo [5/9] Nettoyage des environnements copies de l'autre PC...
if exist "backend\.venv" ( rmdir /s /q "backend\.venv" & echo   - backend\.venv supprime )
if exist ".next" ( rmdir /s /q ".next" & echo   - .next supprime )
:: node_modules peut contenir des binaires natifs compiles pour le Node
:: de l'AUTRE PC -> on le supprime pour forcer npm a recuperer les bons binaires.
if exist "node_modules" ( rmdir /s /q "node_modules" & echo   - node_modules supprime )
echo   [OK] Pret pour une installation propre.
echo.

:: ============================================================ [6/9] Backend Python
echo [6/9] Creation de l'environnement Python et installation des dependances...
echo   ^(cela peut prendre quelques minutes^)
pushd backend
"!MARVIN_PYTHON!" -m venv .venv
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
echo [7/9] Installation reproductible des dependances du frontend ^(npm ci^)...
if exist "package-lock.json" (
    call npm ci
) else (
    call npm install
)
if errorlevel 1 ( echo   [ERREUR] Installation npm echouee. & popd & pause & exit /b 1 )
echo   [OK] Frontend pret.
echo.

:: --- Verification du module natif sharp compile pour CE PC ---
echo   Verification des modules natifs Node...
node -e "require('sharp');" >nul 2>&1
if errorlevel 1 (
    echo   [ATTENTION] Un module natif n'a pas pu se charger. Correction automatique...
    call npm rebuild sharp
)
node -e "require('sharp'); console.log('   [OK] sharp charge.');" 2>nul || echo   [ERREUR] Module natif toujours KO -^> supprimez node_modules puis relancez ce script.
if not exist "node_modules\electron\dist\electron.exe" (
    echo   [INFO] Preparation du runtime optionnel Marvin Avatar...
    node node_modules\electron\install.js
)
if exist "node_modules\electron\dist\electron.exe" (
    echo   [OK] Runtime Marvin Avatar pret.
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-desktop-avatar.ps1"
    if errorlevel 1 (
        echo   [ATTENTION] Raccourci Avatar non cree. Lancez scripts\install-desktop-avatar.ps1 manuellement.
    ) else (
        echo   [OK] Raccourci Marvin Avatar cree sur le Bureau.
    )
) else (
    echo   [ATTENTION] Avatar de bureau indisponible. Le socle Marvin reste utilisable.
)
:: --- Verification que le backend Python importe ---
pushd backend
.venv\Scripts\python -c "import tools, main" >nul 2>&1 && (echo   [OK] Backend Python importe correctement.) || (echo   [ATTENTION] Le backend Python n'importe pas - verifiez requirements.txt.)
popd
echo.

:: ============================================================ [8/9] Modeles IA
echo [8/9] Selection et telechargement des modeles IA locaux adaptes...
echo   Demarrage du service Ollama...
start "" /B "!OLLAMA!" serve >nul 2>&1
timeout /t 4 /nobreak >nul
set "LOCAL_MODEL_PLAN=%TEMP%\marvin-local-model-plan-%RANDOM%.txt"
backend\.venv\Scripts\python.exe scripts\plan_local_models.py > "!LOCAL_MODEL_PLAN!"
if errorlevel 1 (
    echo   [DEGRADE] Detection materielle impossible : aucun modele generatif impose.
) else (
    for /f "usebackq delims=" %%M in ("!LOCAL_MODEL_PLAN!") do (
        echo   - %%M ^(selection dynamique selon GPU, RAM et disque^)...
        "!OLLAMA!" pull "%%M"
        if errorlevel 1 echo   [DEGRADE] %%M indisponible : le portefeuille local sera limite.
    )
)
del "!LOCAL_MODEL_PLAN!" >nul 2>&1
echo   - nomic-embed-text ^(memoire semantique locale^)...
"!OLLAMA!" pull nomic-embed-text
if errorlevel 1 echo   [DEGRADE] nomic-embed-text indisponible : l'indexation semantique sera limitee.
echo   [OK] Le portefeuille local a ete adapte a cette machine.
echo.

:: ============================================================ [9/9] Config
echo [9/9] Configuration...
if not exist "data" mkdir "data"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\manage-data-acl.ps1" -Action Apply -NoConfirm
if errorlevel 1 (
    echo   [ERREUR] Les ACL du dossier data n ont pas pu etre securisees.
    echo   Consultez runtime\security\data-acl-result.json puis relancez l installeur.
    popd & pause & exit /b 1
)
echo   [OK] Donnees Marvin limitees a l utilisateur, SYSTEM et Administrateurs.
echo   [INFO] Les secrets DPAPI restent lies au compte Windows qui les a crees.
echo   [INFO] Apres copie de data sur un autre PC, reconnectez comptes et identifiants.
if not exist ".env.local" if exist ".env.local.example" (
    copy ".env.local.example" ".env.local" >nul
    echo   [OK] .env.local cree ^(modifiez-le pour vos comptes Google/Outlook si besoin^).
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\write-install-report.ps1" >nul
if errorlevel 1 (
    echo   [ATTENTION] Rapport de capacites non genere. Le socle installe reste utilisable.
) else (
    echo   [OK] Rapport portable cree : data\install-capabilities.json
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
echo     -^> http://localhost:8005/api/health   ^(doit afficher version + compteur d'outils^)
echo.
echo   [Optionnel] Generation video IA locale ^(GPU NVIDIA, ~3-5 Go^) :
echo     voir backend\requirements-video.txt
echo.
popd
pause
