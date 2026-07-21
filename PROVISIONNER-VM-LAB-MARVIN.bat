@echo off
setlocal
cd /d "%~dp0"
echo.
echo Marvin VM Lab - Provisionnement Hyper-V controle
echo Les anciennes VM et le reseau physique de l'hote ne seront pas modifies.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""%CD%\scripts\provision-vm-lab.ps1"" -Profile Both -Confirm'"
if errorlevel 1 (
  echo.
  echo [ECHEC] Provisionnement non termine. Consultez les erreurs affichees.
  pause
  exit /b 1
)
echo.
echo [OK] Provisionnement termine. Ouvrez le Gestionnaire Hyper-V pour installer les OS.
pause
endlocal
