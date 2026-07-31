[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [ValidateRange(5, 120)]
    [int]$TimeoutSeconds = 35,
    [switch]$NoForceFallback
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$LifecycleRoot = Join-Path $ProjectRoot 'runtime\lifecycle'
$LogRoot = Join-Path $ProjectRoot 'runtime\logs'
$LogPath = Join-Path $LogRoot 'lifecycle.jsonl'
$Ports = @(3000, 8005, 8443)
$StartedAt = Get-Date

function Rotate-LifecycleLog {
    if (-not (Test-Path -LiteralPath $LogPath)) { return }
    if ((Get-Item -LiteralPath $LogPath).Length -lt 2MB) { return }
    for ($Index = 4; $Index -ge 1; $Index--) {
        $Source = if ($Index -eq 1) { $LogPath } else { "$LogPath.$($Index - 1)" }
        $Destination = "$LogPath.$Index"
        if (Test-Path -LiteralPath $Source) {
            Move-Item -LiteralPath $Source -Destination $Destination -Force
        }
    }
}

function Write-LifecycleEvent {
    param(
        [Parameter(Mandatory = $true)][string]$Action,
        [Parameter(Mandatory = $true)][string]$Result,
        [hashtable]$Context = @{}
    )
    New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
    Rotate-LifecycleLog
    $Event = [ordered]@{
        timestamp = (Get-Date).ToUniversalTime().ToString('o')
        level = if ($Result -eq 'success') { 'INFO' } else { 'ERROR' }
        component = 'marvin-lifecycle'
        action = $Action
        result = $Result
        duration_ms = [math]::Round(((Get-Date) - $StartedAt).TotalMilliseconds)
        context = $Context
    }
    Add-Content -LiteralPath $LogPath -Value ($Event | ConvertTo-Json -Compress -Depth 6) -Encoding UTF8
}

function Test-MarvinProcess {
    param([Parameter(Mandatory = $true)][int]$Id)
    $CurrentId = $Id
    for ($Depth = 0; $Depth -lt 10 -and $CurrentId -gt 0; $Depth++) {
        $Candidate = Get-CimInstance Win32_Process -Filter "ProcessId = $CurrentId" -ErrorAction SilentlyContinue
        if ($null -eq $Candidate) { return $false }
        $Identity = "{0} {1}" -f [string]$Candidate.ExecutablePath, [string]$Candidate.CommandLine
        if ($Identity.IndexOf($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
        $CurrentId = [int]$Candidate.ParentProcessId
    }
    return $false
}

function Get-MarvinListeners {
    $Found = @()
    foreach ($Port in $Ports) {
        foreach ($Connection in @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
            $ProcessId = [int]$Connection.OwningProcess
            $Found += [pscustomobject]@{
                Port = $Port
                ProcessId = $ProcessId
                IsMarvin = Test-MarvinProcess -Id $ProcessId
            }
        }
    }
    return @($Found)
}

function New-ShutdownRequest {
    param([Parameter(Mandatory = $true)][string]$Name)
    New-Item -ItemType Directory -Path $LifecycleRoot -Force | Out-Null
    $Destination = Join-Path $LifecycleRoot $Name
    $Temporary = "$Destination.$PID.tmp"
    [System.IO.File]::WriteAllText($Temporary, (Get-Date).ToUniversalTime().ToString('o'))
    Move-Item -LiteralPath $Temporary -Destination $Destination -Force
}

$Initial = @(Get-MarvinListeners)
$Foreign = @($Initial | Where-Object { -not $_.IsMarvin })
if ($Foreign.Count -gt 0) {
    $Summary = @($Foreign | ForEach-Object { "port $($_.Port), PID $($_.ProcessId)" }) -join '; '
    Write-LifecycleEvent -Action 'shutdown' -Result 'failed' -Context @{ reason = 'foreign_listener'; listeners = $Summary }
    Write-Error "Arrêt refusé : un processus étranger occupe un port Marvin ($Summary)."
    exit 2
}

if ($Initial.Count -eq 0) {
    $Result = [ordered]@{
        success = $true
        state = 'already_stopped'
        graceful = $true
        forced_process_ids = @()
        preserved_ollama = $true
    }
    Write-LifecycleEvent -Action 'shutdown' -Result 'success' -Context @{ state = 'already_stopped' }
    $Result | ConvertTo-Json -Compress
    exit 0
}

if (-not $PSCmdlet.ShouldProcess('Marvin (ports 3000, 8005 et 8443)', 'Arrêt coopératif vérifié')) {
    exit 0
}

New-ShutdownRequest -Name 'backend.shutdown'
New-ShutdownRequest -Name 'frontend.shutdown'

# Caddy possède sa propre API d'administration locale et sait terminer ses
# connexions proprement. Utiliser son contrat natif évite d'attendre le timeout
# général puis de tuer la passerelle HTTPS.
$Caddy = Join-Path $ProjectRoot 'runtime\https\caddy.exe'
$CaddyConfig = Join-Path $ProjectRoot 'runtime\https\caddy.json'
$CaddyStopAttempted = $false
if ((Test-Path -LiteralPath $Caddy) -and (Test-Path -LiteralPath $CaddyConfig)) {
    $HttpsListener = @($Initial | Where-Object { $_.Port -eq 8443 })
    if ($HttpsListener.Count -gt 0) {
        $CaddyStopAttempted = $true
        try {
            $CaddyStop = Start-Process -FilePath $Caddy `
                -ArgumentList @('stop', '--config', $CaddyConfig) `
                -Wait -PassThru -WindowStyle Hidden
            if ($CaddyStop.ExitCode -ne 0) {
                throw "caddy stop a retourné le code $($CaddyStop.ExitCode)"
            }
        } catch {
            Write-Warning "La fermeture coopérative HTTPS a échoué; le repli borné reste actif : $($_.Exception.Message)"
        }
    }
}

$Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    Start-Sleep -Milliseconds 250
    $Remaining = @(Get-MarvinListeners)
} while ($Remaining.Count -gt 0 -and (Get-Date) -lt $Deadline)

$Forced = @()
if ($Remaining.Count -gt 0 -and -not $NoForceFallback) {
    foreach ($Listener in $Remaining) {
        if (-not $Listener.IsMarvin) { continue }
        $ProcessId = [int]$Listener.ProcessId
        try {
            Stop-Process -Id $ProcessId -Force -ErrorAction Stop
            $Forced += $ProcessId
        } catch {
            Write-Warning "Le PID Marvin $ProcessId n'a pas pu être terminé : $($_.Exception.Message)"
        }
    }
    $ForceDeadline = (Get-Date).AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 250
        $Remaining = @(Get-MarvinListeners)
    } while ($Remaining.Count -gt 0 -and (Get-Date) -lt $ForceDeadline)
}

Remove-Item -LiteralPath (Join-Path $LifecycleRoot 'backend.shutdown') -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $LifecycleRoot 'frontend.shutdown') -Force -ErrorAction SilentlyContinue

$Success = $Remaining.Count -eq 0
$Result = [ordered]@{
    success = $Success
    state = if ($Success) { 'stopped' } else { 'failed' }
    graceful = $Success -and $Forced.Count -eq 0
    forced_process_ids = @($Forced | Sort-Object -Unique)
    caddy_stop_attempted = $CaddyStopAttempted
    remaining = @($Remaining | ForEach-Object { @{ port = $_.Port; process_id = $_.ProcessId } })
    preserved_ollama = $true
    duration_ms = [math]::Round(((Get-Date) - $StartedAt).TotalMilliseconds)
}

Write-LifecycleEvent -Action 'shutdown' -Result $(if ($Success) { 'success' } else { 'failed' }) -Context @{
    graceful = $Result.graceful
    forced_process_ids = $Result.forced_process_ids
    caddy_stop_attempted = $CaddyStopAttempted
    remaining = $Result.remaining
}
$Result | ConvertTo-Json -Compress -Depth 6
if (-not $Success) { exit 1 }
