# Demarre (ou redemarre) l'instance SearXNG locale de Marvin et configure automatiquement
# le reglage searxng_url -- pense pour etre relancable tel quel sur n'importe quelle
# nouvelle machine Marvin (portable, pas de config manuelle apres ce script).
#
# Usage : powershell -ExecutionPolicy Bypass -File docker\searxng\start-searxng.ps1
#         (ou double-clic sur INSTALLER-SEARXNG.bat a la racine du depot)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = 8890
$backendUrl = "http://127.0.0.1:8005"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# -- 1. Docker CLI present ? --------------------------------------------------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker n'est pas installe. Installe Docker Desktop puis relance ce script: https://www.docker.com/products/docker-desktop/" -ForegroundColor Red
    exit 1
}

# -- 2. Daemon Docker demarre ? Sinon, lancer Docker Desktop et attendre ----
Write-Step "Verification du demon Docker..."
$dockerReady = $false
try { docker info *>$null; if ($LASTEXITCODE -eq 0) { $dockerReady = $true } } catch {}

if (-not $dockerReady) {
    Write-Step "Demon Docker arrete -- demarrage de Docker Desktop..."
    $dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerDesktop) {
        Start-Process $dockerDesktop
    } else {
        Write-Host "Docker Desktop introuvable a l'emplacement attendu. Demarre-le manuellement puis relance ce script." -ForegroundColor Red
        exit 1
    }
    $attempts = 0
    while (-not $dockerReady -and $attempts -lt 60) {
        Start-Sleep -Seconds 3
        try { docker info *>$null; if ($LASTEXITCODE -eq 0) { $dockerReady = $true } } catch {}
        $attempts++
    }
    if (-not $dockerReady) {
        Write-Host "Docker Desktop n'a pas demarre a temps (3 min). Reessaie une fois qu'il est pret." -ForegroundColor Red
        exit 1
    }
}
Write-Host "Demon Docker pret." -ForegroundColor Green

# -- 3. Config locale (secret genere au premier lancement, jamais committe) --
$settingsPath = Join-Path $here "settings.yml"
if (-not (Test-Path $settingsPath)) {
    Write-Step "Generation de settings.yml (cle secrete locale)..."
    $template = Get-Content (Join-Path $here "settings.yml.example") -Raw
    $secret = -join ((1..32) | ForEach-Object { "{0:x}" -f (Get-Random -Maximum 16) })
    $template.Replace("CHANGE_ME_AUTO_GENERATED", $secret) | Set-Content -Path $settingsPath -Encoding utf8 -NoNewline
}

# -- 4. docker compose up -d --------------------------------------------------
Write-Step "Demarrage du conteneur SearXNG (port $port)..."
Push-Location $here
try {
    docker compose up -d
    if ($LASTEXITCODE -ne 0) { throw "docker compose up a echoue (code $LASTEXITCODE)" }
} finally {
    Pop-Location
}

# -- 5. Attendre que l'API JSON reponde reellement ---------------------------
Write-Step "Attente de la disponibilite de l'API JSON..."
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest "http://localhost:$port/search?q=test&format=json" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $healthy = $true; break }
    } catch {}
}
if (-not $healthy) {
    Write-Host "SearXNG ne repond pas encore apres 1 min. Verifie 'docker logs marvin-searxng'." -ForegroundColor Yellow
    exit 1
}
Write-Host "SearXNG repond correctement sur http://localhost:$port" -ForegroundColor Green

# -- 6. Configurer Marvin automatiquement (searxng_url) ----------------------
Write-Step "Configuration de Marvin (searxng_url)..."
try {
    $body = @{ value = "http://localhost:$port" } | ConvertTo-Json
    Invoke-RestMethod -Uri "$backendUrl/api/credentials/searxng_url" -Method Put -Body $body -ContentType "application/json" | Out-Null
    Write-Host "Marvin utilisera desormais SearXNG en priorite pour ses recherches web." -ForegroundColor Green
} catch {
    Write-Host "Marvin ne semble pas demarre (backend inaccessible sur $backendUrl) -- configure searxng_url manuellement plus tard dans Reglages > Connexions, valeur: http://localhost:$port" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Termine. Instance: http://localhost:$port  |  Conteneur: marvin-searxng" -ForegroundColor Cyan
