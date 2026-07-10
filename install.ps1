# ============================================================
# SecretaryAI — Installateur Windows automatique
# Exécuter avec : powershell -ExecutionPolicy Bypass -File install.ps1
# ============================================================

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$APP_NAME = "SecretaryAI"
$APP_DIR  = "$env:USERPROFILE\SecretaryAI"
$REPO_URL = "https://github.com/VOTRE_USERNAME/secretary-ai"   # <-- À remplacer

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    [!!] $msg" -ForegroundColor Yellow }

Write-Host @"
  ____                    _                     _    ___
 / ___|  ___  ___ _ __ ___| |_ __ _ _ __ _   _  / \  |_ _|
 \___ \ / _ \/ __| '__/ _ \ __/ _` | '__| | | |/ _ \  | |
  ___) |  __/ (__| | |  __/ || (_| | |  | |_| / ___ \ | |
 |____/ \___|\___|_|  \___|\__\__,_|_|   \__, /_/   \_\___|
                                          |___/
                 Installateur Windows v1.0
"@ -ForegroundColor Magenta

# ── 1. Node.js ───────────────────────────────────────────────
Write-Step "Vérification de Node.js..."
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) {
    $nodeVer = (node --version)
    Write-OK "Node.js déjà installé : $nodeVer"
} else {
    Write-Step "Téléchargement de Node.js LTS..."
    $nodeInstaller = "$env:TEMP\node_installer.msi"
    Invoke-WebRequest "https://nodejs.org/dist/lts/node-v20.x.x-x64.msi" -OutFile $nodeInstaller -UseBasicParsing
    Write-Step "Installation de Node.js (peut prendre 1-2 minutes)..."
    Start-Process msiexec.exe -ArgumentList "/i `"$nodeInstaller`" /quiet /norestart" -Wait
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
    Write-OK "Node.js installé."
}

# ── 2. Ollama ─────────────────────────────────────────────────
Write-Step "Vérification d'Ollama..."
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaCmd) {
    Write-OK "Ollama déjà installé."
} else {
    Write-Step "Téléchargement d'Ollama..."
    $ollamaInstaller = "$env:TEMP\OllamaSetup.exe"
    Invoke-WebRequest "https://ollama.com/download/OllamaSetup.exe" -OutFile $ollamaInstaller -UseBasicParsing
    Write-Step "Installation d'Ollama..."
    Start-Process $ollamaInstaller -ArgumentList "/S" -Wait
    $env:PATH += ";$env:LOCALAPPDATA\Programs\Ollama"
    Write-OK "Ollama installé."
}

# ── 3. Démarrer Ollama en arrière-plan ────────────────────────
Write-Step "Démarrage du service Ollama..."
$ollamaRunning = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ollamaRunning) {
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
    Write-OK "Ollama démarré."
} else {
    Write-OK "Ollama tourne déjà."
}

# ── 4. Télécharger le modèle IA recommandé ────────────────────
Write-Step "Téléchargement du modèle IA hermes3:8b (peut prendre 5-10 min selon votre connexion)..."
Write-Warn "Si le modèle est déjà présent, cette étape sera rapide."
$models = (ollama list 2>$null) -join " "
if ($models -like "*hermes3*") {
    Write-OK "Modèle hermes3 déjà présent."
} else {
    ollama pull hermes3:8b
    Write-OK "Modèle hermes3:8b téléchargé."
}

# ── 5. Copier/cloner les fichiers de SecretaryAI ─────────────
Write-Step "Installation de SecretaryAI dans $APP_DIR..."
if (-not (Test-Path $APP_DIR)) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    if (Test-Path "$scriptDir\package.json") {
        # Copie locale depuis le répertoire du script
        Write-Step "Copie des fichiers depuis le répertoire local..."
        Copy-Item $scriptDir $APP_DIR -Recurse -Force
        Write-OK "Fichiers copiés dans $APP_DIR"
    } else {
        Write-Warn "Répertoire source non trouvé. Clonez d'abord le dépôt ou modifiez REPO_URL."
        Write-Host "    Vous pouvez aussi copier manuellement les fichiers dans : $APP_DIR" -ForegroundColor Yellow
    }
}

# ── 6. Installation des dépendances npm ──────────────────────
Write-Step "Installation des dépendances npm..."
Push-Location $APP_DIR
npm install --prefer-offline 2>&1 | Out-Null
Write-OK "Dépendances installées."

# ── 7. Build Next.js ─────────────────────────────────────────
Write-Step "Compilation de l'application (peut prendre 1-2 minutes)..."
npm run build 2>&1 | Select-Object -Last 5 | ForEach-Object { Write-Host "    $_" }
Write-OK "Application compilée."
Pop-Location

# ── 8. Créer start.bat ────────────────────────────────────────
Write-Step "Création du lanceur start.bat..."
$startBat = @"
@echo off
title SecretaryAI
echo Démarrage de SecretaryAI...

:: Démarrer Ollama si nécessaire
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I "ollama.exe" >NUL
if %ERRORLEVEL% NEQ 0 (
    echo Démarrage d'Ollama en arrière-plan...
    start "" /B ollama serve
    timeout /t 3 /nobreak >NUL
)

:: Lancer SecretaryAI
cd /d "$APP_DIR"
npm start

pause
"@
Set-Content "$APP_DIR\start.bat" $startBat -Encoding utf8
Write-OK "Lanceur start.bat créé."

# ── 9. Raccourci sur le Bureau ────────────────────────────────
Write-Step "Création du raccourci sur le Bureau..."
$WshShell = New-Object -ComObject WScript.Shell
$shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\SecretaryAI.lnk")
$shortcut.TargetPath = "$APP_DIR\start.bat"
$shortcut.WorkingDirectory = $APP_DIR
$shortcut.Description = "Lancer SecretaryAI"
$shortcut.Save()
Write-OK "Raccourci créé sur le Bureau."

# ── 10. Optionnel : démarrage automatique avec Windows ────────
$autostart = Read-Host "`nVoulez-vous que SecretaryAI démarre automatiquement avec Windows ? (o/n)"
if ($autostart -eq 'o' -or $autostart -eq 'O' -or $autostart -eq 'y' -or $autostart -eq 'Y') {
    $regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    Set-ItemProperty -Path $regPath -Name "SecretaryAI" -Value "`"$APP_DIR\start.bat`""
    Write-OK "Démarrage automatique configuré."
}

# ── Résumé ─────────────────────────────────────────────────────
Write-Host @"

╔══════════════════════════════════════════════════════╗
║          SecretaryAI installé avec succès !          ║
╠══════════════════════════════════════════════════════╣
║  Dossier : $APP_DIR
║  Lanceur : Bureau → SecretaryAI.lnk
║  Modèle  : hermes3:8b (Ollama)
║  URL     : http://localhost:3000
╚══════════════════════════════════════════════════════╝

Double-cliquez sur l'icône SecretaryAI sur votre Bureau
pour lancer l'assistant. Bonne utilisation !
"@ -ForegroundColor Green
