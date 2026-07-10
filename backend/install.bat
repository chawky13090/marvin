@echo off
title SecretaryAI - Installation Backend Python
cd /d "%~dp0"
echo.
echo  =========================================
echo    SecretaryAI - Installation du backend
echo  =========================================
echo.

python --version >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERREUR] Python 3.10+ requis. Téléchargez sur https://www.python.org/
    pause & exit /b 1
)

echo [1/4] Création de l'environnement virtuel Python...
if exist ".venv" (
    echo       Environnement existant supprimé pour réinstallation propre.
    rmdir /s /q .venv
)
python -m venv .venv

echo [2/4] Mise à jour de pip...
.venv\Scripts\python -m pip install --upgrade pip --quiet

echo [3/4] Installation des dépendances (peut prendre quelques minutes)...
.venv\Scripts\pip install -r requirements.txt

echo [4/4] Post-installation pywin32 (accès Windows API)...
.venv\Scripts\python .venv\Scripts\pywin32_postinstall.py -install 2>NUL

echo.
echo  Installation terminée !
echo  Lancez le backend avec : start.bat
echo.
pause
