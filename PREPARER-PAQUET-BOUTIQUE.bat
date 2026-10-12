@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title Marvin - Export du paquet boutique
pushd "%~dp0" || exit /b 1

set "BUILDER=%~dp0scripts\build-marvin-windows-package.ps1"
set "SIGNER=%~dp0scripts\build-marvin-private-signed-package.ps1"
set "OUTPUT=%~dp0dist"

echo.
echo ================================================================
echo   MARVIN - PREPARATION DU PAQUET BOUTIQUE
echo ================================================================
echo.
echo Le paquet sera construit exclusivement depuis le commit Git courant.
echo Les conversations, memoires, secrets, configurations locales, caches,
echo environnements Python, node_modules et fichiers non suivis sont exclus.
echo.

if not exist "%BUILDER%" (
    echo [ERREUR] Constructeur securise introuvable :
    echo          %BUILDER%
    popd
    pause
    exit /b 2
)
if not exist "%SIGNER%" (
    echo [ERREUR] Constructeur de signature privee introuvable :
    echo          %SIGNER%
    popd
    pause
    exit /b 7
)

where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Windows PowerShell est introuvable.
    popd
    pause
    exit /b 3
)

echo [1/5] Construction propre et reproductible...
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass ^
    -File "%BUILDER%" -OutputDirectory "%OUTPUT%"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo.
    echo [ERREUR] Construction refusee ^(code %RESULT%^).
    echo Le depot suivi doit etre propre. Aucun paquet incomplet ne doit etre transfere.
    popd
    pause
    exit /b %RESULT%
)

echo.
echo [2/5] Recherche du paquet produit...
set "PACKAGE="
for /f "delims=" %%F in ('dir /b /a-d /o-d "%OUTPUT%\Marvin-Windows-v*.zip" 2^>nul') do if not defined PACKAGE set "PACKAGE=%OUTPUT%\%%F"

if not defined PACKAGE (
    echo [ERREUR] Aucun ZIP Marvin n'a ete produit dans "%OUTPUT%".
    popd
    pause
    exit /b 4
)
if not exist "%PACKAGE%.sha256" (
    echo [ERREUR] Empreinte externe absente : "%PACKAGE%.sha256"
    popd
    pause
    exit /b 5
)

echo [3/5] Verification SHA-256 du ZIP...
powershell.exe -NoProfile -NonInteractive -Command ^
    "$zip='%PACKAGE%'; $expected=((Get-Content -LiteralPath ($zip+'.sha256') -Raw).Trim() -split '\s+')[0].ToLowerInvariant(); $stream=[IO.File]::OpenRead($zip); $hasher=[Security.Cryptography.SHA256]::Create(); try{$actual=([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-','').ToLowerInvariant()}finally{$hasher.Dispose();$stream.Dispose()}; if($expected -notmatch '^[0-9a-f]{64}$' -or $actual -ne $expected){Write-Error 'Empreinte SHA-256 invalide.'; exit 6}; $size=[math]::Round((Get-Item -LiteralPath $zip).Length/1MB,2); Write-Host ('[OK] Integrite verifiee - '+$size+' Mio - SHA-256 '+$actual)"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    popd
    pause
    exit /b %RESULT%
)

echo [4/5] Creation de l'installateur EXE et signature Authenticode privee...
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass ^
    -File "%SIGNER%" -ZipPath "%PACKAGE%" -OutputDirectory "%OUTPUT%"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo [ERREUR] Signature privee impossible ^(code %RESULT%^).
    popd
    pause
    exit /b %RESULT%
)

set "SIGNED_PACKAGE="
for /f "delims=" %%F in ('dir /b /a-d /o-d "%OUTPUT%\Marvin-Setup-Private-v*.exe" 2^>nul') do if not defined SIGNED_PACKAGE set "SIGNED_PACKAGE=%OUTPUT%\%%F"
if not defined SIGNED_PACKAGE (
    echo [ERREUR] Installateur EXE signe introuvable.
    popd
    pause
    exit /b 8
)
echo [5/5] Relecture de la signature et de l'editeur...
powershell.exe -NoProfile -NonInteractive -Command ^
    "Import-Module -Name '%SystemRoot%\System32\WindowsPowerShell\v1.0\Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1' -Force -ErrorAction Stop; $s=Get-AuthenticodeSignature -LiteralPath '%SIGNED_PACKAGE%'; if($null -eq $s.SignerCertificate -or $s.SignerCertificate.Subject -notlike '*CN=Marvin Private Publisher*'){Write-Error 'Signataire Marvin invalide.';exit 9}; Write-Host ('[OK] Signature presente - '+$s.SignerCertificate.Subject+' - statut local '+$s.Status)"
if errorlevel 1 (
    popd
    pause
    exit /b 9
)

echo.
echo ================================================================
echo   PAQUET BOUTIQUE PRET
echo ================================================================
echo.
echo A transferer ensemble :
echo   %SIGNED_PACKAGE%
echo   %SIGNED_PACKAGE%.sha256
echo   %OUTPUT%\Marvin-Private-Publisher.cer
echo   %OUTPUT%\Marvin-Private-Publisher.cer.sha256
echo   %OUTPUT%\Marvin-Private-Root.cer
echo   %OUTPUT%\Marvin-Private-Root.cer.sha256
echo   %OUTPUT%\trust-marvin-private-publisher.ps1
echo   %OUTPUT%\FAIRE-CONFIANCE-A-MARVIN.bat
echo   %OUTPUT%\RETIRER-CONFIANCE-MARVIN.bat
echo.
echo Sur le poste cible : verifier l'empreinte communiquee separement, lancer
echo FAIRE-CONFIANCE-A-MARVIN.bat, puis Marvin-Setup-Private-vX.Y.Z.exe.
echo Cette signature est privee et ne remplace pas une signature publique Microsoft.
echo Le profil Full exige Docker Desktop et SearXNG; leur licence doit etre
echo acceptee explicitement. Le profil Core degrade reste un choix volontaire.
echo.
popd
pause
exit /b 0
