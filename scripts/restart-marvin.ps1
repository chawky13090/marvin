[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [ValidateRange(30, 180)][int]$StartupTimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$StartedAt = Get-Date

if (-not $PSCmdlet.ShouldProcess('Marvin', 'Redémarrage vérifié')) { exit 0 }

$StopOutput = @(& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
    -File (Join-Path $PSScriptRoot 'stop-marvin.ps1'))
if ($LASTEXITCODE -ne 0) {
    throw "L'arrêt Marvin a échoué : $($StopOutput -join ' ')"
}

$StartProcess = Start-Process -FilePath $env:ComSpec `
    -ArgumentList @('/d', '/c', ("call `"{0}`"" -f (Join-Path $Root 'start.bat'))) `
    -WorkingDirectory $Root -WindowStyle Normal -PassThru

$Deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
$Backend = $null
$FrontendReady = $false
$StableChecks = 0
do {
    try { $Backend = Invoke-RestMethod 'http://127.0.0.1:8005/api/health' -TimeoutSec 3 } catch { $Backend = $null }
    try {
        $FrontendReady = (Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:3000/api/status' -TimeoutSec 3).StatusCode -eq 200
    } catch { $FrontendReady = $false }
    if ($null -ne $Backend -and $FrontendReady) {
        $StableChecks++
        if ($StableChecks -ge 3) { break }
    } else {
        $StableChecks = 0
    }
    if ($StartProcess.HasExited -and $StartProcess.ExitCode -ne 0) { break }
    Start-Sleep -Milliseconds 1000
} while ((Get-Date) -lt $Deadline)

if ($null -eq $Backend -or -not $FrontendReady) {
    [pscustomobject]@{
        success = $false
        state = 'failed'
        reason = 'startup_timeout_or_exit'
        launcher_exit_code = if ($StartProcess.HasExited) { $StartProcess.ExitCode } else { $null }
        duration_ms = [math]::Round(((Get-Date) - $StartedAt).TotalMilliseconds)
    } | ConvertTo-Json -Compress
    exit 1
}

$Status = $null
$StatusDeadline = $Deadline
do {
    $StatusJson = & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File (Join-Path $PSScriptRoot 'get-marvin-runtime-status.ps1')
    $Status = $StatusJson | ConvertFrom-Json
    if ($Status.overall -in @('ready', 'degraded')) { break }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $StatusDeadline)

$FinalSuccess = $null -ne $Status -and $Status.overall -in @('ready', 'degraded')
[pscustomobject]@{
    success = $FinalSuccess
    state = if ($null -ne $Status) { $Status.overall } else { 'failed' }
    version = [string]$Backend.version
    tools = [int]$Backend.tools_count
    dependencies = $Status.dependencies
    readiness = $Status.readiness
    lan = $Status.lan
    duration_ms = [math]::Round(((Get-Date) - $StartedAt).TotalMilliseconds)
} | ConvertTo-Json -Compress -Depth 6
if (-not $FinalSuccess) { exit 1 }
