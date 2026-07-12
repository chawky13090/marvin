@echo off
chcp 65001 >nul
title Marvin - Demarrage automatique
pushd "%~dp0"

echo.
echo  ==============================================================
echo     Marvin - Enregistrer le demarrage automatique
echo  ==============================================================
echo.
echo  Cree une tache planifiee Windows qui relance Marvin tout seul
echo  a chaque demarrage du serveur (apres un reboot ou une coupure),
echo  sans qu'il faille double-cliquer sur un script a la main.
echo  Ouvre aussi le pare-feu Windows pour que les autres postes de la
echo  boutique puissent acceder a Marvin sur le reseau local (LAN).
echo.
echo  ATTENTION : necessite les droits administrateur.
echo.

:: Verifie les droits admin (schtasks + regles pare-feu les exigent)
net session >nul 2>&1
if errorlevel 1 (
    echo   [ERREUR] Ce script doit etre execute EN TANT QU'ADMINISTRATEUR
    echo   ^(clic droit -^> "Executer en tant qu'administrateur"^).
    popd & pause & exit /b 1
)

:: v2.180 -- demande explicitement ("marvin doit etre accessible sur le lan de la
:: boutique... incorporer cela dans les reglages de la version installable"). Jusqu'ici
:: une commande PowerShell a copier-coller a la main dans INSTALLATION.md -- maintenant
:: automatique, dans le script de configuration serveur deja admin. Idempotent : New-
:: NetFirewallRule avec -ErrorAction SilentlyContinue si la regle existe deja (relancer
:: ce script plusieurs fois ne cree pas de doublons).
echo [1/2] Ouverture du pare-feu Windows pour l'acces reseau (LAN)...
powershell -NoProfile -Command ^
    "Get-NetFirewallRule -DisplayName 'Marvin - Frontend' -ErrorAction SilentlyContinue | Remove-NetFirewallRule; " ^
    "Get-NetFirewallRule -DisplayName 'Marvin - Backend' -ErrorAction SilentlyContinue | Remove-NetFirewallRule; " ^
    "New-NetFirewallRule -DisplayName 'Marvin - Frontend' -Direction Inbound -LocalPort 3000 -Protocol TCP -Action Allow | Out-Null; " ^
    "New-NetFirewallRule -DisplayName 'Marvin - Backend' -Direction Inbound -LocalPort 8005 -Protocol TCP -Action Allow | Out-Null; " ^
    "Write-Host '  [OK] Ports 3000 (frontend) et 8005 (backend) ouverts sur le reseau local.'"
if errorlevel 1 (
    echo   [ATTENTION] L'ouverture du pare-feu a echoue -- Marvin restera accessible en local uniquement.
    echo   Vous pouvez le faire manuellement plus tard ^(voir INSTALLATION.md, etape 4^).
)
echo.

echo [2/2] Enregistrement de la tache planifiee...
set "TASK_NAME=Marvin - Demarrage automatique"
set "SCRIPT_PATH=%~dp0START-PRODUCTION.bat"

schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if not errorlevel 1 (
    echo   Une tache "%TASK_NAME%" existe deja -^> suppression avant recreation...
    schtasks /delete /tn "%TASK_NAME%" /f >nul
)

:: v2.176 -- /RU SYSTEM : demarre AVANT toute ouverture de session utilisateur,
:: ideal pour un serveur qui doit repartir seul apres un reboot. Contrepartie
:: connue et documentee (INSTALLATION.md) : une tache SYSTEM tourne sans session
:: de bureau interactive -- les fonctionnalites qui en dependent (notifications
:: visuelles Windows, presse-papiers) peuvent etre indisponibles. Si ces
:: fonctionnalites sont utilisees au quotidien sur ce serveur, remplacez /RU
:: SYSTEM par un compte utilisateur dedie (schtasks demandera son mot de passe)
:: et activez l'ouverture de session automatique de ce compte dans Windows.
schtasks /create /tn "%TASK_NAME%" /tr "\"%SCRIPT_PATH%\"" /sc onstart /ru SYSTEM /rl highest /f

if errorlevel 1 (
    echo   [ERREUR] La creation de la tache planifiee a echoue.
    popd & pause & exit /b 1
)

echo.
echo   [OK] Tache planifiee creee : "%TASK_NAME%"
echo   Marvin demarrera automatiquement a chaque redemarrage du serveur.
echo.
echo   Pour tester tout de suite sans redemarrer :
echo     schtasks /run /tn "%TASK_NAME%"
echo.
echo   Pour la retirer plus tard :
echo     schtasks /delete /tn "%TASK_NAME%" /f
echo.
popd
pause
