@echo off
title SecretaryAI - Backend Python
cd /d "%~dp0"
:: Les journaux Marvin contiennent des accents et emojis. Sans UTF-8, certaines consoles
:: Windows CP1252 font échouer FastAPI dès le premier print du lifespan.
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
echo.
echo  ====================================
echo    SecretaryAI - Backend Python
echo  ====================================
echo.

:: Installer les dépendances si besoin
if not exist ".venv\Scripts\python.exe" (
    :: Python systeme n'est requis que pour CREER le venv. Une fois le venv pret,
    :: Marvin demarre directement avec son interpreteur isole.
    python --version >NUL 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo [ERREUR] Python est requis pour creer backend\.venv.
        echo Lancez INSTALLER-NOUVEAU-PC.bat.
        pause
        exit /b 1
    )
    echo [1/3] Création de l'environnement virtuel Python...
    python -m venv .venv
    echo [2/3] Installation des dépendances...
    .venv\Scripts\python -m pip install -r requirements.txt
    echo [3/3] Post-installation pywin32...
    .venv\Scripts\python .venv\Scripts\pywin32_postinstall.py -install 2>NUL
    echo       Installation terminée.
) else (
    echo [*] Environnement virtuel existant trouvé.
)

echo.
echo  Backend disponible sur : http://localhost:8005
echo  Documentation API      : http://localhost:8005/docs
echo  Appuyez sur Ctrl+C pour arrêter.
echo.

.venv\Scripts\python -c "import fastapi, uvicorn, qdrant_client" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERREUR] Le venv existe mais des dependances backend manquent.
    echo Lancez INSTALLER-NOUVEAU-PC.bat pour le regenerer proprement.
    pause
    exit /b 1
)

.venv\Scripts\python server_supervisor.py
exit /b %ERRORLEVEL%
