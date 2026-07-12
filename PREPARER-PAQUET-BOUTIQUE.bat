@echo off
chcp 65001 >nul
title Marvin - Preparer un paquet propre pour un nouveau deploiement
setlocal enabledelayedexpansion
pushd "%~dp0"

echo.
echo  ==============================================================
echo     Marvin - Preparer un paquet PROPRE pour un nouveau serveur
echo  ==============================================================
echo.
echo  Ce script cree une COPIE du projet, SANS vos donnees personnelles :
echo    - data\             ^(conversations, memoire, captures d'ecran,
echo                          sauvegardes, jeton eleve, competences apprises^)
echo    - backend\data\     ^(cle de compte de service Google si presente^)
echo    - backend\.venv, node_modules, .next   ^(specifiques a CETTE machine^)
echo    - .env.local        ^(vos identifiants locaux^)
echo    - .git              ^(historique de developpement, inutile sur le serveur^)
echo.
echo  Un simple copier-coller du dossier "secretary-ai" embarquerait TOUT
echo  cela par erreur -- vos conversations et memoires personnelles se
echo  retrouveraient sur le serveur de la boutique. Ce script evite ca.
echo.
pause
echo.

set "DEST=%~dp0..\marvin-boutique-paquet"
if exist "!DEST!" (
    echo [1/2] Un paquet existe deja dans "!DEST!" -^> suppression avant recreation...
    rmdir /s /q "!DEST!"
)
mkdir "!DEST!"

echo [1/2] Copie du projet ^(sans les dossiers personnels/specifiques a cette machine^)...
:: robocopy /XD exclut des DOSSIERS entiers ; /XF exclut des FICHIERS precis.
:: Code de sortie robocopy < 8 = succes (meme avec des fichiers copies, ce qui
:: est le cas normal) -- seul un code >= 8 est une vraie erreur.
robocopy "%~dp0." "!DEST!" /E /NFL /NDL /NJH /NJS ^
    /XD ".git" "data" "backend\data" ".venv" "node_modules" ".next" "__pycache__" ".pytest_cache" "generated_videos" "backend\generated_videos" ^
    /XF ".env.local" "*.pyc" "*.log" "last-event.json" "streamText.txt" "test_ai.js" "_mining_ui.png"
if !ERRORLEVEL! GEQ 8 (
    echo   [ERREUR] La copie a echoue ^(code robocopy !ERRORLEVEL!^).
    popd & pause & exit /b 1
)
echo   [OK] Copie propre creee dans : !DEST!
echo.

echo [2/2] Verification -- aucune donnee personnelle ne doit apparaitre ci-dessous :
if exist "!DEST!\data" ( echo   [ATTENTION] data\ present -^> NE PAS transferer tel quel ! ) else ( echo   [OK] Aucun dossier data\ )
if exist "!DEST!\backend\data" ( echo   [ATTENTION] backend\data\ present -^> NE PAS transferer tel quel ! ) else ( echo   [OK] Aucun backend\data\ )
if exist "!DEST!\.env.local" ( echo   [ATTENTION] .env.local present -^> NE PAS transferer tel quel ! ) else ( echo   [OK] Aucun .env.local )
echo.

echo  ==============================================================
echo     PAQUET PRET
echo  ==============================================================
echo.
echo   Dossier a transferer sur le nouveau serveur ^(cle USB, partage reseau^) :
echo     !DEST!
echo.
echo   Sur le serveur, suivez ensuite INSTALLATION.md en partant de l'etape 1
echo   ^(INSTALLER-NOUVEAU-PC.bat cree un data\ tout NEUF et vide automatiquement --
echo   rien a faire de plus^).
echo.
popd
pause
