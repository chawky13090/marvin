@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title Marvin - Export du paquet boutique
pushd "%~dp0" || exit /b 1

set "BUILDER=%~dp0scripts\build-marvin-windows-package.ps1"
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

where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Windows PowerShell est introuvable.
    popd
    pause
    exit /b 3
)

echo [1/3] Construction propre et reproductible...
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
echo [2/3] Recherche du paquet produit...
set "PACKAGE="
for /f "usebackq delims=" %%F in (`powershell.exe -NoProfile -NonInteractive -Command ^
    "$f=Get-ChildItem -LiteralPath '%OUTPUT%' -Filter 'Marvin-Windows-v*.zip' -File ^| Sort-Object LastWriteTimeUtc -Descending ^| Select-Object -First 1; if($f){$f.FullName}"`) do set "PACKAGE=%%F"

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

echo [3/3] Verification SHA-256 du ZIP...
powershell.exe -NoProfile -NonInteractive -Command ^
    "$zip='%PACKAGE%'; $expected=((Get-Content -LiteralPath ($zip+'.sha256') -Raw).Trim() -split '\s+')[0].ToLowerInvariant(); $stream=[IO.File]::OpenRead($zip); $hasher=[Security.Cryptography.SHA256]::Create(); try{$actual=([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-','').ToLowerInvariant()}finally{$hasher.Dispose();$stream.Dispose()}; if($expected -notmatch '^[0-9a-f]{64}$' -or $actual -ne $expected){Write-Error 'Empreinte SHA-256 invalide.'; exit 6}; $size=[math]::Round((Get-Item -LiteralPath $zip).Length/1MB,2); Write-Host ('[OK] Integrite verifiee - '+$size+' Mio - SHA-256 '+$actual)"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    popd
    pause
    exit /b %RESULT%
)

echo.
echo ================================================================
echo   PAQUET BOUTIQUE PRET
echo ================================================================
echo.
echo A transferer ensemble :
echo   %PACKAGE%
echo   %PACKAGE%.sha256
echo.
echo Sur le poste cible : extraire le ZIP puis double-cliquer sur
echo INSTALLER-MARVIN.bat. Docker, Hyper-V et Ollama Cloud restent optionnels.
echo.
popd
pause
exit /b 0
