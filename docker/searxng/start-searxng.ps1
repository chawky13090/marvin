# Demarre (ou redemarre) l'instance SearXNG locale de Marvin et configure automatiquement
# le reglage searxng_url -- pense pour etre relancable tel quel sur n'importe quelle
# nouvelle machine Marvin (portable, pas de config manuelle apres ce script).
#
# Usage : powershell -ExecutionPolicy Bypass -File docker\searxng\start-searxng.ps1
#         (ou double-clic sur INSTALLER-SEARXNG.bat a la racine du depot)

[CmdletBinding()]
param(
    [ValidateRange(1, 30)]
    [int]$DockerProbeTimeoutSeconds = 5,
    [ValidateRange(30, 600)]
    [int]$DockerStartupTimeoutSeconds = 180,
    [ValidateSet('manual', 'marvin-background')]
    [string]$StartupOrigin = 'manual',
    [ValidateRange(1, 168)]
    [int]$StartupBackoffHours = 24,
    [switch]$LockSelfTest,
    [ValidateRange(0, 10000)]
    [int]$LockSelfTestHoldMilliseconds = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendUrl = "http://127.0.0.1:8005"
$stateRoot = [System.IO.Path]::GetFullPath((Join-Path $here '..\..\runtime\searxng'))
$dockerBackoffPath = Join-Path $stateRoot 'docker-startup-backoff.json'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Test-DockerStartupBackoff {
    if (-not (Test-Path -LiteralPath $dockerBackoffPath -PathType Leaf)) {
        return $false
    }
    try {
        $State = Get-Content -LiteralPath $dockerBackoffPath -Raw -ErrorAction Stop | ConvertFrom-Json
        $RecordedAt = [DateTimeOffset]::Parse([string]$State.recorded_at_utc)
        return $RecordedAt.AddHours($StartupBackoffHours) -gt [DateTimeOffset]::UtcNow
    } catch {
        # Un état illisible ne doit jamais bloquer Docker indéfiniment.
        Remove-Item -LiteralPath $dockerBackoffPath -Force -ErrorAction SilentlyContinue
        return $false
    }
}

function Set-DockerStartupBackoff([string]$Reason) {
    [System.IO.Directory]::CreateDirectory($stateRoot) | Out-Null
    $Payload = [ordered]@{
        schema_version = 1
        recorded_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        reason = $Reason
        automatic_retry_after_hours = $StartupBackoffHours
        user_data_modified = $false
    } | ConvertTo-Json -Depth 4
    $Temporary = $dockerBackoffPath + '.new'
    [System.IO.File]::WriteAllText($Temporary, $Payload, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $Temporary -Destination $dockerBackoffPath -Force
}

function Clear-DockerStartupBackoff {
    Remove-Item -LiteralPath $dockerBackoffPath -Force -ErrorAction SilentlyContinue
}

function Test-DockerDaemon([string]$DockerPath, [int]$TimeoutSeconds) {
    $Stdout = [System.IO.Path]::GetTempFileName()
    $Stderr = [System.IO.Path]::GetTempFileName()
    try {
        $Process = Start-Process -FilePath $DockerPath `
            -ArgumentList @('info', '--format', '{{.ServerVersion}}') `
            -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
        if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
            & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
            return $false
        }
        # Windows PowerShell 5.1 ne peuple pas toujours ExitCode après la
        # surcharge WaitForExit(timeout). Le second appel finalise les handles
        # natifs déjà terminés sans ajouter d'attente.
        $Process.WaitForExit()
        $Process.Refresh()
        # Une sonde Docker n'est recevable que si le CLI termine sans erreur ET
        # renvoie réellement une version serveur. Les avertissements non fatals
        # sur stderr restent compatibles avec un démon fonctionnel.
        $ServerVersion = [System.IO.File]::ReadAllText($Stdout).Trim()
        return (
            [int]$Process.ExitCode -eq 0 -and
            $ServerVersion -match '^\d+\.\d+(?:\.\d+)?(?:[-+].*)?$'
        )
    } catch {
        return $false
    } finally {
        Remove-Item -LiteralPath $Stdout, $Stderr -Force -ErrorAction SilentlyContinue
    }
}

function Get-ExistingSearxngPort([string]$DockerPath) {
    $Stdout = [System.IO.Path]::GetTempFileName()
    $Stderr = [System.IO.Path]::GetTempFileName()
    try {
        $Process = Start-Process -FilePath $DockerPath `
            -ArgumentList @('port', 'marvin-searxng', '8080/tcp') `
            -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
        if (-not $Process.WaitForExit(10000)) {
            & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
            return $null
        }
        $Process.WaitForExit()
        $Process.Refresh()
        if ([int]$Process.ExitCode -ne 0) { return $null }
        $Mapped = [System.IO.File]::ReadAllText($Stdout).Trim()
        $Match = [regex]::Match($Mapped, ':(\d+)$')
        if (-not $Match.Success) { return $null }
        return [int]$Match.Groups[1].Value
    } catch {
        return $null
    } finally {
        Remove-Item -LiteralPath $Stdout, $Stderr -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-DockerComposeUp([string]$DockerPath, [string]$WorkingDirectory) {
    $Stdout = [System.IO.Path]::GetTempFileName()
    $Stderr = [System.IO.Path]::GetTempFileName()
    try {
        $Process = Start-Process -FilePath $DockerPath `
            -ArgumentList @('compose', 'up', '-d', '--remove-orphans') `
            -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
        if (-not $Process.WaitForExit(900000)) {
            & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
            throw 'docker compose up a depasse quinze minutes.'
        }
        $Process.WaitForExit()
        $Process.Refresh()
        if ([int]$Process.ExitCode -ne 0) {
            $Details = ([System.IO.File]::ReadAllText($Stderr) + [System.IO.File]::ReadAllText($Stdout)).Trim()
            if ($Details.Length -gt 4000) { $Details = $Details.Substring($Details.Length - 4000) }
            throw "docker compose up a echoue (code $($Process.ExitCode)): $Details"
        }
    } finally {
        Remove-Item -LiteralPath $Stdout, $Stderr -Force -ErrorAction SilentlyContinue
    }
}

$script:DetectedDockerCrashLine = $null
$script:LastRecoveredDockerCrashLine = $null

function Test-DockerStaleSocketCrash {
    $LogPath = Join-Path $env:LOCALAPPDATA 'Docker\log\host\com.docker.backend.exe.log'
    if (-not (Test-Path -LiteralPath $LogPath -PathType Leaf)) {
        return $false
    }
    try {
        # Docker répète ensuite le dialogue d'erreur et peut repousser la ligne
        # causale loin de la queue immédiate. On recherche donc plus largement,
        # mais on exige un horodatage récent et on ne répare jamais deux fois
        # le même crash. La signature reste indépendante de la langue OS.
        $RecentLines = @(Get-Content -LiteralPath $LogPath -Tail 500 -ErrorAction Stop)
        $Signature = 'backend crashed, dumping error.*initializing (Inference manager|Secrets Engine):.*(dockerInference|engine\.sock): remove .*\(listener:'
        $CrashLine = @($RecentLines | Where-Object { $_ -match $Signature } | Select-Object -Last 1)
        if ($CrashLine.Count -ne 1 -or $CrashLine[0] -eq $script:LastRecoveredDockerCrashLine) {
            return $false
        }
        $TimestampMatch = [regex]::Match([string]$CrashLine[0], '^\[(?<timestamp>[^\]]+)\]')
        if (-not $TimestampMatch.Success) {
            return $false
        }
        $CrashAt = [DateTimeOffset]::MinValue
        if (-not [DateTimeOffset]::TryParse($TimestampMatch.Groups['timestamp'].Value, [ref]$CrashAt)) {
            return $false
        }
        if ($CrashAt -lt [DateTimeOffset]::UtcNow.AddMinutes(-30)) {
            return $false
        }
        $script:DetectedDockerCrashLine = [string]$CrashLine[0]
        return $true
    } catch {
        return $false
    }
}

function Set-DockerOptionalAiDisabled {
    $SettingsPath = Join-Path $env:APPDATA 'Docker\settings-store.json'
    if (-not (Test-Path -LiteralPath $SettingsPath -PathType Leaf)) {
        throw "Configuration Docker Desktop introuvable: $SettingsPath"
    }
    $BackupPath = $SettingsPath + '.pre-marvin-socket-recovery-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
    Copy-Item -LiteralPath $SettingsPath -Destination $BackupPath -ErrorAction Stop
    $Settings = Get-Content -LiteralPath $SettingsPath -Raw -ErrorAction Stop | ConvertFrom-Json
    foreach ($Entry in @{
        EnableDockerAI = $false
        EnableInference = $false
        EnableInferenceGPUVariant = $false
    }.GetEnumerator()) {
        $Settings | Add-Member -NotePropertyName $Entry.Key -NotePropertyValue $Entry.Value -Force
    }
    $TemporaryPath = $SettingsPath + '.marvin-new'
    $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($TemporaryPath, ($Settings | ConvertTo-Json -Depth 20), $Utf8NoBom)
    Move-Item -LiteralPath $TemporaryPath -Destination $SettingsPath -Force
    Write-Host "Configuration Docker sauvegardee: $BackupPath" -ForegroundColor Yellow
}

function Repair-DockerStaleSocketCrash {
    if (-not (Test-DockerStaleSocketCrash)) {
        return $false
    }
    $script:LastRecoveredDockerCrashLine = $script:DetectedDockerCrashLine
    Write-Step 'Crash Docker AF_UNIX detecte -- recuperation reversible des runtimes optionnels...'
    Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -in @('Docker Desktop', 'com.docker.backend', 'docker', 'dockerd')
    } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    $Remaining = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -in @('Docker Desktop', 'com.docker.backend', 'docker', 'dockerd')
    })
    if ($Remaining.Count -gt 0) {
        throw 'La recuperation Docker est refusee: des processus Docker restent actifs.'
    }
    Set-DockerOptionalAiDisabled
    $LocalRoot = [System.IO.Path]::GetFullPath($env:LOCALAPPDATA)
    foreach ($RelativePath in @('Docker\run', 'docker-secrets-engine')) {
        $Target = [System.IO.Path]::GetFullPath((Join-Path $LocalRoot $RelativePath))
        if (-not $Target.StartsWith($LocalRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Chemin runtime Docker hors profil refuse: $Target"
        }
        if (Test-Path -LiteralPath $Target) {
            $Parent = Split-Path -Parent $Target
            $Leaf = Split-Path -Leaf $Target
            $Preserved = Join-Path $Parent ($Leaf + '.stale-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff'))
            Move-Item -LiteralPath $Target -Destination $Preserved -ErrorAction Stop
            Write-Host "Runtime Docker preserve: $Preserved" -ForegroundColor Yellow
        }
    }
    return $true
}

# Le canari concurrent doit mesurer sa propre exclusion sans entrer en
# concurrence avec un bootstrap SearXNG reel deja actif pendant le gate live.
$StartupMutexName = if ($LockSelfTest) {
    'Local\Marvin.SearXNG.Startup.SelfTest'
} else {
    'Local\Marvin.SearXNG.Startup'
}
$StartupMutex = [System.Threading.Mutex]::new($false, $StartupMutexName)
$OwnsStartupMutex = $false
try {
    try {
        $OwnsStartupMutex = $StartupMutex.WaitOne(0)
    } catch [System.Threading.AbandonedMutexException] {
        $OwnsStartupMutex = $true
    }
    if (-not $OwnsStartupMutex) {
        Write-Output 'already_running'
        exit 0
    }
    if ($LockSelfTest) {
        if ($LockSelfTestHoldMilliseconds -gt 0) {
            Start-Sleep -Milliseconds $LockSelfTestHoldMilliseconds
        }
        Write-Output 'lock_acquired'
        exit 0
    }

# -- 1. Docker CLI present ? --------------------------------------------------
    $DockerCommand = Get-Command docker -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $DockerCommand) {
    Write-Host "Docker n'est pas installe. Installe Docker Desktop puis relance ce script: https://www.docker.com/products/docker-desktop/" -ForegroundColor Red
    exit 1
    }
$DockerPath = [string]$DockerCommand.Source

# -- 2. Daemon Docker demarre ? Sinon, lancer Docker Desktop et attendre ----
Write-Step "Verification du demon Docker..."
$dockerReady = Test-DockerDaemon -DockerPath $DockerPath -TimeoutSeconds $DockerProbeTimeoutSeconds

if (-not $dockerReady) {
    if ($StartupOrigin -eq 'marvin-background' -and (Test-DockerStartupBackoff)) {
        Write-Host "Docker reste indisponible après un échec récent. Démarrage automatique différé; Marvin continue sans SearXNG." -ForegroundColor Yellow
        exit 2
    }
    Write-Step "Demon Docker arrete -- demarrage de Docker Desktop..."
    $dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerDesktop) {
        Start-Process $dockerDesktop -WindowStyle Hidden
    } else {
        Write-Host "Docker Desktop introuvable a l'emplacement attendu. Demarre-le manuellement puis relance ce script." -ForegroundColor Red
        exit 1
    }
    $DockerDeadline = [DateTimeOffset]::UtcNow.AddSeconds($DockerStartupTimeoutSeconds)
    $SocketRecoveryAttempts = 0
    $MaxSocketRecoveryAttempts = 3
    while (-not $dockerReady -and [DateTimeOffset]::UtcNow -lt $DockerDeadline) {
        Start-Sleep -Seconds 3
        if (
            $SocketRecoveryAttempts -lt $MaxSocketRecoveryAttempts -and
            (Test-DockerStaleSocketCrash)
        ) {
            $SocketRecoveryAttempts += 1
            if (Repair-DockerStaleSocketCrash) {
                Start-Process $dockerDesktop -WindowStyle Hidden
            }
        }
        $RemainingSeconds = [math]::Max(1, [math]::Ceiling(($DockerDeadline - [DateTimeOffset]::UtcNow).TotalSeconds))
        $ProbeSeconds = [math]::Min($DockerProbeTimeoutSeconds, $RemainingSeconds)
        $dockerReady = Test-DockerDaemon -DockerPath $DockerPath -TimeoutSeconds $ProbeSeconds
    }
    if (-not $dockerReady) {
        Set-DockerStartupBackoff -Reason 'docker_daemon_startup_failed'
        Write-Host "Docker Desktop n'a pas demarre dans la borne de $DockerStartupTimeoutSeconds secondes. Reessaie une fois qu'il est pret." -ForegroundColor Red
        exit 1
    }
}
Clear-DockerStartupBackoff
Write-Host "Demon Docker pret." -ForegroundColor Green

# -- 2b. Port loopback libre et non exclu par Hyper-V/WSL --------------------
Write-Step "Selection d'un port SearXNG local disponible..."
$port = $null
$candidate = Get-ExistingSearxngPort -DockerPath $DockerPath
if ($null -ne $candidate) {
    try {
        $probe = Invoke-WebRequest "http://127.0.0.1:$candidate/config" -UseBasicParsing -TimeoutSec 3
        if ($probe.StatusCode -eq 200) { $port = $candidate }
    } catch {}
}
if ($null -eq $port) {
    $portOutput = @(& (Join-Path $PSScriptRoot '..\..\scripts\resolve-searxng-port.ps1'))
    if ($portOutput.Count -eq 0) {
        throw "Impossible de sélectionner un port local pour SearXNG."
    }
    $port = [int]$portOutput[-1]
}
$env:SEARXNG_PORT = [string]$port
Write-Host "Port SearXNG selectionne : $port (loopback uniquement)." -ForegroundColor Green

# -- 3. Config locale (secret genere au premier lancement, jamais committe) --
$settingsPath = Join-Path $here "settings.yml"
$templatePath = Join-Path $here "settings.yml.example"
if (-not (Test-Path $settingsPath)) {
    Write-Step "Generation de settings.yml (cle secrete locale)..."
    $template = Get-Content $templatePath -Raw
    $secret = -join ((1..32) | ForEach-Object { "{0:x}" -f (Get-Random -Maximum 16) })
    $template.Replace("CHANGE_ME_AUTO_GENERATED", $secret) | Set-Content -Path $settingsPath -Encoding utf8 -NoNewline
} else {
    # Le fichier contient un secret local et reste gitignore. Synchroniser les
    # réglages versionnés sans changer ce secret, avec une sauvegarde atomique
    # exploitable si le nouveau pool de moteurs doit être annulé.
    $currentSettings = Get-Content $settingsPath -Raw
    $secretMatch = [regex]::Match($currentSettings, 'secret_key:\s*"([^"]+)"')
    if (-not $secretMatch.Success) {
        throw "settings.yml ne contient pas de secret_key valide; synchronisation refusee."
    }
    $template = Get-Content $templatePath -Raw
    $expectedSettings = $template.Replace("CHANGE_ME_AUTO_GENERATED", $secretMatch.Groups[1].Value)
    if ($currentSettings -ne $expectedSettings) {
        Write-Step "Mise a jour controlee de settings.yml (secret conserve)..."
        Copy-Item -LiteralPath $settingsPath -Destination ($settingsPath + ".bak") -Force
        $expectedSettings | Set-Content -Path $settingsPath -Encoding utf8 -NoNewline
    }
}

# -- 4. docker compose up -d --------------------------------------------------
Write-Step "Demarrage du conteneur SearXNG (port $port)..."
$env:MARVIN_SEARXNG_CONFIG_SHA256 = (Get-FileHash -LiteralPath $settingsPath -Algorithm SHA256).Hash.ToLowerInvariant()
Push-Location $here
try {
    # Compose recrée seulement si l'image, le port ou l'empreinte des réglages
    # change. Un start.bat redondant ne coupe donc plus la recherche en cours.
    Invoke-DockerComposeUp -DockerPath $DockerPath -WorkingDirectory $here
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

# -- 6. Verifier la configuration effectivement chargee ----------------------
Write-Step "Verification du pool de moteurs effectivement charge..."
$requiredEngines = @("bing", "google cse", "google news", "startpage", "qwant", "mojeek", "yahoo")
try {
    $runtimeConfig = Invoke-RestMethod -Uri "http://localhost:$port/config" -TimeoutSec 10
    $enabledEngines = @($runtimeConfig.engines | Where-Object { $_.enabled } | ForEach-Object { $_.name })
    $missingEngines = @($requiredEngines | Where-Object { $_ -notin $enabledEngines })
    if ($missingEngines.Count -gt 0) {
        throw "Configuration non chargee; moteurs absents: $($missingEngines -join ', ')"
    }
    $requiredTabs = @("general", "images", "videos", "news", "map", "music", "it", "science", "files", "social media", "shopping")
    $emptyOrFragileTabs = @()
    foreach ($tab in $requiredTabs) {
        $tabCount = @(
            $runtimeConfig.engines |
                Where-Object { $_.enabled -and ($_.categories -contains $tab) }
        ).Count
        if ($tabCount -lt 2) {
            $emptyOrFragileTabs += "$tab=$tabCount"
        }
    }
    if ($emptyOrFragileTabs.Count -gt 0) {
        throw "Onglets sans redondance moteur: $($emptyOrFragileTabs -join ', ')"
    }
    Write-Host "$($enabledEngines.Count) moteurs actifs; tous les onglets ont au moins deux moteurs." -ForegroundColor Green
} catch {
    Write-Host "Le conteneur repond mais son pool de moteurs est invalide: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Rollback local: Copy-Item '$settingsPath.bak' '$settingsPath' -Force puis relancer ce script." -ForegroundColor Yellow
    exit 1
}

# -- 7. Configurer Marvin automatiquement (searxng_url) ----------------------
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
} finally {
    if ($OwnsStartupMutex) {
        try { $StartupMutex.ReleaseMutex() } catch {}
    }
    $StartupMutex.Dispose()
}
