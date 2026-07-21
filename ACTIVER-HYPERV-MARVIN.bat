@echo off
setlocal EnableExtensions
cd /d "%~dp0"

fltmc >nul 2>&1
if errorlevel 1 (
    echo Demande d'autorisation administrateur pour le role Hyper-V...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Configuration de l'acces Hyper-V pour %COMPUTERNAME%\%USERNAME%...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\grant-hyperv-access-admin.ps1" -Principal "%COMPUTERNAME%\%USERNAME%" -Confirmed
if errorlevel 1 (
    echo.
    echo [ECHEC] L'acces Hyper-V n'a pas ete configure.
    echo Consultez data\hyperv-access-result.json.
    pause
    exit /b 1
)

echo.
echo [OK] Le compte possede maintenant le role Administrateurs Hyper-V.
echo Le reseau physique de l'hote n'a pas ete modifie.
echo Fermez puis rouvrez votre session Windows avant de relancer Marvin.
pause
exit /b 0
