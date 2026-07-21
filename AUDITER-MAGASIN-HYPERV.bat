@echo off
setlocal
cd /d "%~dp0"
echo.
echo Audit en lecture seule du magasin Hyper-V
echo Aucune VM, aucun disque et aucun reseau ne seront modifies.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""%CD%\scripts\audit-hyperv-store-admin.ps1""'"
echo.
if exist "data\hyperv-store-audit.json" (
  echo [OK] Rapport cree : data\hyperv-store-audit.json
) else (
  echo [ECHEC] Aucun rapport cree. Verifiez que l UAC a ete accepte.
)
pause
endlocal
