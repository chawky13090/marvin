@echo off
setlocal
cd /d "%~dp0"
if not exist "node_modules\electron\dist\electron.exe" (
  echo [ERREUR] Electron est absent. Executez INSTALLER-NOUVEAU-PC.bat puis reessayez.
  pause
  exit /b 1
)
start "Marvin Avatar" /b "node_modules\electron\dist\electron.exe" "desktop-avatar\main.cjs"
exit /b 0
