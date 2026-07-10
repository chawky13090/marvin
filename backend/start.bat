@echo off
title SecretaryAI - Backend Python
cd /d "%~dp0"
echo.
echo  ====================================
echo    SecretaryAI - Backend Python
echo  ====================================
echo.

:: Vérifier si Python est installé
python --version >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERREUR] Python n'est pas installé ou pas dans le PATH.
    echo Téléchargez-le sur https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Installer les dépendances si besoin
if not exist ".venv" (
    echo [1/3] Création de l'environnement virtuel Python...
    python -m venv .venv
    echo [2/3] Installation des dépendances...
    .venv\Scripts\pip install -r requirements.txt
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

.venv\Scripts\uvicorn main:app --host 0.0.0.0 --port 8005

pause
