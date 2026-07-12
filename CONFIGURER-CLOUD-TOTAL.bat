@echo off
chcp 65001 >nul
title Marvin - Configurer le mode Cloud Total (serveur sans GPU)
pushd "%~dp0"

echo.
echo  ==============================================================
echo     Marvin - Mode Cloud Total (pour un serveur SANS GPU)
echo  ==============================================================
echo.
echo  Equivalent au preset "Ultra debride" de Reglages -^> Modele IA,
echo  applique ici directement via l'API -- pratique sur un serveur sans
echo  navigateur/ecran a portee de main.
echo.
echo  Ce que ca change :
echo    - TOUT part au cloud (agent/chat/analyse), y compris les donnees
echo      normalement gardees en local par prudence (emails, mots de
echo      passe, SSH, factures) -- plus aucune exception de sensibilite.
echo.
echo  Ce qui NE change PAS (jamais desactive, quel que soit le mode) :
echo    - Le garde-fou systeme contre les commandes destructrices
echo      (formatage disque, suppression systeme...).
echo    - L'OCR/vision generaliste (photos, scans) reste LOCAL par
echo      defaut -- plus lent sans GPU, mais rien d'envoye au cloud pour
echo      ce type de contenu potentiellement sensible (factures clients...).
echo      Seul le pipeline dedie "captures d'ecran -^> documentation"
echo      utilise le cloud, en connaissance de cause.
echo.
pause
echo.

echo [0/3] Detection d'une carte graphique...
:: v2.179 -- garde-fou demande explicitement : ce mode est fait pour un serveur SANS GPU
:: (ex. boutique), jamais pour un poste de travail normal (comme la machine de developpement
:: de l'utilisateur, qui a un GPU et fonctionne tres bien en local). Si une VRAIE carte
:: graphique est detectee (pas l'adaptateur d'affichage generique de Windows), on demande une
:: confirmation EXPLICITE tapee au clavier -- plus dur a valider par erreur qu'un simple Entree.
for /f "usebackq delims=" %%g in (`powershell -NoProfile -Command ^
    "(Get-CimInstance Win32_VideoController | Where-Object { $_.Name -notmatch 'Basic Display|Remote Display|Microsoft Hyper-V' } | Select-Object -First 1).Name"`) do set "GPU_FOUND=%%g"

if not "%GPU_FOUND%"=="" (
    echo.
    echo   [ATTENTION] Une carte graphique a ete detectee sur CETTE machine : %GPU_FOUND%
    echo   Ce script est prevu pour un serveur SANS GPU ^(ex. serveur boutique^). Sur une
    echo   machine avec GPU ^(comme un poste de travail normal^), Marvin fonctionne deja bien
    echo   en local -- ce mode envoie inutilement vos donnees sensibles au cloud.
    echo.
    set /p "CONFIRM_GPU=  Tapez OUI en majuscules pour continuer quand meme : "
    if not "%CONFIRM_GPU%"=="OUI" (
        echo   Annule.
        popd & pause & exit /b 1
    )
) else (
    echo   [OK] Aucun GPU detecte -- coherent avec un serveur boutique.
)
echo.

echo [1/3] Verification que le backend Marvin repond...
powershell -NoProfile -Command "try { Invoke-RestMethod -Uri 'http://127.0.0.1:8005/api/health' -TimeoutSec 5 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo   [ERREUR] Backend injoignable sur http://127.0.0.1:8005 -- demarrez Marvin d'abord ^(START-PRODUCTION.bat^).
    popd & pause & exit /b 1
)
echo   [OK] Backend joignable.
echo.

echo [2/3] Choix du meilleur modele cloud installe...
:: v2.179 -- resolu par le backend (cloud_routing.pick_best_cloud_model), meme logique
:: EXACTE que le preset "Ultra debride" de l'UI (Reglages) -- un seul endroit a maintenir.
:: Jamais un nom de modele fige en dur ici : un modele cloud recommande peut etre retire
:: par le fournisseur en quelques jours (constate en reel).
for /f "usebackq delims=" %%m in (`powershell -NoProfile -Command ^
    "(Invoke-RestMethod -Uri 'http://127.0.0.1:8005/api/cloud/best-model?need=general').model"`) do set "BEST_MODEL=%%m"

if "%BEST_MODEL%"=="" (
    echo   [ERREUR] Aucun modele cloud installe ^(attendu : un nom se terminant par ":cloud" ou "-cloud"^).
    echo   Installez-en un d'abord, ex. : ollama pull deepseek-v4-flash:cloud
    popd & pause & exit /b 1
)
echo   [OK] Modele choisi : %BEST_MODEL%
echo.

echo [3/3] Application de la configuration...
powershell -NoProfile -Command ^
    "$best = '%BEST_MODEL%'; " ^
    "Invoke-RestMethod -Method Put -Uri 'http://127.0.0.1:8005/api/settings/local_only_lockdown' -ContentType 'application/json' -Body (@{value=$false} | ConvertTo-Json) | Out-Null; " ^
    "Invoke-RestMethod -Method Put -Uri 'http://127.0.0.1:8005/api/settings/cloud_enabled' -ContentType 'application/json' -Body (@{value=$true} | ConvertTo-Json) | Out-Null; " ^
    "Invoke-RestMethod -Method Put -Uri 'http://127.0.0.1:8005/api/settings/cloud_overrides' -ContentType 'application/json' -Body (@{value=@{agent=$best; chat=$best; analysis=$best}} | ConvertTo-Json) | Out-Null; " ^
    "Invoke-RestMethod -Method Put -Uri 'http://127.0.0.1:8005/api/settings/ultra_unrestricted' -ContentType 'application/json' -Body (@{value=$true} | ConvertTo-Json) | Out-Null; " ^
    "Write-Host '  [OK] Configuration appliquee.'"
if errorlevel 1 (
    echo   [ERREUR] L'application de la configuration a echoue.
    popd & pause & exit /b 1
)
echo.

echo  ==============================================================
echo     MODE CLOUD TOTAL ACTIF
echo  ==============================================================
echo.
echo   Modele utilise pour agent/chat/analyse : %BEST_MODEL%
echo   Verifiable dans Reglages -^> Modele IA ^(carte "Ultra debride" active^).
echo.
popd
pause
