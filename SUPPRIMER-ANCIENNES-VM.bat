@echo off
setlocal
cd /d "%~dp0"
echo.
echo Suppression des anciennes VM Hyper-V
echo Les VM dont le nom commence par Marvin- sont toujours preservees.
echo Le reseau physique et les commutateurs Hyper-V ne sont pas modifies.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""%CD%\scripts\remove-legacy-hyperv-vms.ps1"" -Confirmed -Confirm:$false'"
echo.
echo Resultat: data\hyperv-legacy-removal-result.json
pause
endlocal
