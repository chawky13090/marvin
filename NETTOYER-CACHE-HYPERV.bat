@echo off
setlocal
cd /d "%~dp0"
echo.
echo Nettoyage transactionnel des inscriptions Hyper-V orphelines
echo 12 VM fantomes et 13 anciens checkpoints seront sauvegardes puis retires.
echo Les deux VM Marvin, les commutateurs et le reseau physique seront preserves.
echo Pour un resultat fiable, utilisez clic droit puis Executer en tant qu administrateur.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\invoke-cleanup-hyperv.ps1"
echo.
if exist "data\hyperv-orphan-cleanup-result.json" (
  echo [OK] Rapport cree : data\hyperv-orphan-cleanup-result.json
) else (
  echo [ECHEC] Aucun rapport cree. Lisez le message de la fenetre administrateur.
)
pause
endlocal
