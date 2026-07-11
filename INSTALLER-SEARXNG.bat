@echo off
REM Installe/démarre la recherche web auto-hébergée (SearXNG) pour Marvin.
REM Nécessite Docker Desktop (installé séparément : https://www.docker.com/products/docker-desktop/).
REM Configure automatiquement Marvin pour l'utiliser une fois prêt.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0docker\searxng\start-searxng.ps1"
pause
