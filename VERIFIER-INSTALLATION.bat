@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Marvin - Verification de l'installation (Docteur)
color 0B
pushd "%~dp0"
set PROBLEMS=0

echo.
echo  ==============================================================
echo     Marvin / SecretaryAI - Docteur d'installation
echo  ==============================================================
echo.

:: ===================================================== 1. PREREQUIS
echo [1] Prerequis
where python >nul 2>&1 && ( for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo    [OK] %%v ) || ( echo    [X] Python introuvable ^(installez Python 3.13^) & set /a PROBLEMS+=1 )
where node >nul 2>&1 && ( for /f %%v in ('node --version') do echo    [OK] Node.js %%v ) || ( echo    [X] Node.js introuvable ^(installez Node LTS^) & set /a PROBLEMS+=1 )
where ollama >nul 2>&1 && ( echo    [OK] Ollama installe ) || ( if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" ( echo    [OK] Ollama installe ) else ( echo    [X] Ollama introuvable & set /a PROBLEMS+=1 ) )
echo.

:: ===================================================== 2. BACKEND PYTHON
echo [2] Backend Python
if exist "backend\.venv\Scripts\python.exe" ( echo    [OK] Environnement .venv present ) else ( echo    [X] .venv manquant -^> lancez INSTALLER-NOUVEAU-PC.bat & set /a PROBLEMS+=1 )
if exist "backend\.venv\Scripts\python.exe" (
    pushd backend
    .venv\Scripts\python -c "import tools, main; print('   [OK] Backend importe -', len(tools.TOOLS_REGISTRY), 'outils')" 2>nul || ( echo    [X] Le backend Python n'importe pas -^> pip install -r requirements.txt & set /a PROBLEMS+=1 )
    popd
)
echo.

:: ===================================================== 3. FRONTEND NODE
echo [3] Frontend Node
if exist "node_modules" ( echo    [OK] node_modules present ) else ( echo    [X] node_modules manquant -^> npm install & set /a PROBLEMS+=1 )
node -e "require('better-sqlite3'); require('sharp'); console.log('   [OK] Modules natifs OK (better-sqlite3, sharp)')" 2>nul || ( echo    [X] Module natif KO -^> npm rebuild better-sqlite3 sharp  ^(ou supprimez node_modules + npm install^) & set /a PROBLEMS+=1 )
echo.

:: ===================================================== 4. OLLAMA + MODELES + GPU
echo [4] Ollama, modeles et GPU
python -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=6)); m=[x['name'] for x in d.get('models',[])]; print('   [OK] Ollama joignable -', len(m), 'modele(s):', ', '.join(m) if m else 'AUCUN (faites: ollama pull qwen2.5:7b)')" 2>nul || ( echo    [X] Ollama injoignable sur 127.0.0.1:11434 -^> demarrez-le: ollama serve & set /a PROBLEMS+=1 )
if exist "backend\.venv\Scripts\python.exe" (
    pushd backend
    .venv\Scripts\python -c "import local_video as l; d=l.get_device_info(); print('   [INFO] GPU:', d.get('device_name'), '('+str(d.get('vendor'))+')', '- generation video IA:', 'OUI' if d.get('video_gen_supported') else 'non (NVIDIA/CUDA requis)')" 2>nul || echo    [INFO] Detection GPU indisponible
    .venv\Scripts\python -c "import importlib.util as u; from pathlib import Path; deps=bool(u.find_spec('torch')) and bool(u.find_spec('diffusers')); hub=Path.home()/'.cache'/'huggingface'/'hub'; n=len([d for d in hub.iterdir() if d.is_dir() and d.name.startswith('models--')]) if hub.exists() else 0; print('   [INFO] Video IA - deps (torch+diffusers):', 'OUI' if deps else 'non (optionnel, requirements-video.txt)'); print('   [INFO] Video IA - cache HF (~/.cache/huggingface):', (str(n)+' modele(s) en cache') if hub.exists() else 'vide (DL auto au 1er usage, NVIDIA requis)')" 2>nul
    popd
)
echo.

:: ===================================================== 5. SERVICES EN COURS
echo [5] Services en cours d'execution
python -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:8005/api/health',timeout=6)); print('   [OK] Backend en marche - v'+d['version'], '-', d['tools_count'], 'outils - ollama:', d['ollama'])" 2>nul || echo    [..] Backend non lance ^(port 8005^) - normal s'il n'est pas demarre
python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000',timeout=6); print('   [OK] Frontend en marche (port 3000)')" 2>nul || echo    [..] Frontend non lance ^(port 3000^) - normal s'il n'est pas demarre
echo.

:: ===================================================== 6. CONFIG
echo [6] Configuration
if exist ".env.local" ( echo    [OK] .env.local present ) else ( echo    [..] .env.local absent - sera cree depuis .env.local.example au 1er lancement )
if exist "data" ( echo    [OK] dossier data present ) else ( echo    [..] dossier data absent - sera cree automatiquement )
echo.

:: ===================================================== RESULTAT
echo  ==============================================================
if !PROBLEMS! EQU 0 (
    color 0A
    echo     RESULTAT : TOUT EST OK -^> Marvin est pret a demarrer.
    echo     Lancez  start.bat  puis ouvrez  http://localhost:3000
) else (
    color 0E
    echo     RESULTAT : !PROBLEMS! probleme(s) detecte(s) - voir les [X] ci-dessus.
    echo     La plupart se reglent en relancant  INSTALLER-NOUVEAU-PC.bat
)
echo  ==============================================================
echo.
popd
pause
