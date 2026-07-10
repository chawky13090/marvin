@echo off
chcp 65001 >nul
title SecretaryAI — Installation
color 0B

echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║    🤖 SecretaryAI — Installation             ║
echo  ║    Agent IA Secrétaire Intelligent           ║
echo  ╚══════════════════════════════════════════════╝
echo.

:: ── Vérifier les droits admin ────────────────────
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [INFO] Certaines installations nécessitent les droits administrateur.
    echo [INFO] Relancez ce script en tant qu'administrateur si nécessaire.
    echo.
)

:: ── Vérifier Node.js ─────────────────────────────
echo [1/4] Vérification de Node.js...
where node >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] Node.js non trouvé. Installation en cours...
    winget install OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
    if %ERRORLEVEL% NEQ 0 (
        echo [ERREUR] Impossible d'installer Node.js automatiquement.
        echo          Téléchargez-le manuellement : https://nodejs.org
        pause
        exit /b 1
    )
    :: Rafraîchir le PATH
    set "PATH=%ProgramFiles%\nodejs;%PATH%"
    echo [OK] Node.js installé avec succès !
) else (
    for /f "tokens=*" %%v in ('node --version') do echo [OK] Node.js %%v détecté
)
echo.

:: ── Vérifier Ollama ──────────────────────────────
echo [2/4] Vérification d'Ollama...
where ollama >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
        echo [OK] Ollama trouvé dans %LOCALAPPDATA%\Programs\Ollama
        set "OLLAMA_PATH=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    ) else (
        echo [!] Ollama non trouvé. Installation en cours...
        winget install Ollama.Ollama --accept-package-agreements --accept-source-agreements
        if %ERRORLEVEL% NEQ 0 (
            echo [ERREUR] Impossible d'installer Ollama automatiquement.
            echo          Téléchargez-le manuellement : https://ollama.com/download
            pause
            exit /b 1
        )
        set "OLLAMA_PATH=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
        echo [OK] Ollama installé avec succès !
    )
) else (
    echo [OK] Ollama détecté dans le PATH
    set "OLLAMA_PATH=ollama"
)
echo.

:: ── Installer les dépendances npm ────────────────
echo [3/4] Installation des dépendances Node.js...
call npm install
if %ERRORLEVEL% NEQ 0 (
    echo [ERREUR] L'installation des dépendances a échoué.
    pause
    exit /b 1
)
echo [OK] Dépendances installées !
echo.

:: ── Télécharger le modèle IA ─────────────────────
echo [4/4] Téléchargement du modèle IA (qwen3:8b)...
echo [INFO] Cela peut prendre plusieurs minutes selon votre connexion...

:: S'assurer qu'Ollama est lancé
start /B "" "%OLLAMA_PATH%" serve >nul 2>&1
timeout /t 3 /nobreak >nul

"%OLLAMA_PATH%" pull qwen3:8b
if %ERRORLEVEL% NEQ 0 (
    echo [AVERTISSEMENT] Le téléchargement du modèle a échoué.
    echo                 Assurez-vous qu'Ollama est lancé et réessayez.
    echo                 Commande : ollama pull qwen3:8b
)
echo.

:: ── Créer le fichier .env.local ──────────────────
if not exist ".env.local" (
    copy ".env.local.example" ".env.local" >nul
    echo [OK] Fichier .env.local créé. Modifiez-le pour configurer vos comptes.
)

:: ── Terminé ! ────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║    ✅ Installation terminée !                 ║
echo  ║                                              ║
echo  ║    Pour lancer SecretaryAI :                 ║
echo  ║    → Double-cliquez sur start.bat            ║
echo  ║    → Ou tapez : npm run dev                  ║
echo  ║                                              ║
echo  ║    L'application s'ouvrira sur :             ║
echo  ║    http://localhost:3000                     ║
echo  ╚══════════════════════════════════════════════╝
echo.
pause
