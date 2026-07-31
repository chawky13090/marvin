[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('acquire', 'release', 'signal-stop', 'clear-stop', 'stop-requested')]
    [string]$Action,
    [ValidateRange(30, 3600)][int]$StaleAfterSeconds = 900,
    [ValidateRange(5, 180)][int]$WaitSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Lifecycle = Join-Path $Root 'runtime\lifecycle'
$LockPath = Join-Path $Lifecycle 'startup.lock'
$StopPath = Join-Path $Lifecycle 'stop.requested'
New-Item -ItemType Directory -Path $Lifecycle -Force | Out-Null

if ($Action -eq 'acquire') {
    if (Test-Path -LiteralPath $LockPath) {
        $Age = ((Get-Date) - (Get-Item -LiteralPath $LockPath).LastWriteTime).TotalSeconds
        $OwnerAlive = $false
        try {
            $Existing = Get-Content -LiteralPath $LockPath -Raw | ConvertFrom-Json
            $Owner = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$Existing.owner_process_id)" -ErrorAction SilentlyContinue
            $OwnerAlive = $null -ne $Owner
        } catch {}
        if (-not $OwnerAlive -or $Age -gt $StaleAfterSeconds) {
            Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
        }
    }
    try {
        $Stream = [System.IO.File]::Open($LockPath, 'CreateNew', 'Write', 'None')
        try {
            $Current = Get-CimInstance Win32_Process -Filter "ProcessId = $PID"
            $OwnerProcessId = [int]$Current.ParentProcessId
            $FallbackOwnerProcessId = $OwnerProcessId
            $OwnerMatched = $false
            for ($Depth = 0; $Depth -lt 6 -and $OwnerProcessId -gt 0; $Depth++) {
                $Parent = Get-CimInstance Win32_Process -Filter "ProcessId = $OwnerProcessId" -ErrorAction SilentlyContinue
                if ($null -eq $Parent) { break }
                if ([string]$Parent.CommandLine -match '(?i)(?:^|[\\/\s])(?:START-PRODUCTION|start)\.bat(?:\s|$|\")') {
                    $OwnerMatched = $true
                    break
                }
                $OwnerProcessId = [int]$Parent.ParentProcessId
            }
            if (-not $OwnerMatched) { $OwnerProcessId = $FallbackOwnerProcessId }
            $Payload = [System.Text.Encoding]::UTF8.GetBytes((@{
                process_id = $PID
                owner_process_id = $OwnerProcessId
                created_at = (Get-Date).ToUniversalTime().ToString('o')
            } | ConvertTo-Json -Compress))
            $Stream.Write($Payload, 0, $Payload.Length)
            $Stream.Flush($true)
        } finally {
            $Stream.Dispose()
        }
        Remove-Item -LiteralPath $StopPath -Force -ErrorAction SilentlyContinue
        Write-Output 'acquired'
        exit 0
    } catch [System.IO.IOException] {
        Write-Output 'busy'
        exit 3
    }
}

if ($Action -eq 'release') {
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
    Write-Output 'released'
    exit 0
}

if ($Action -eq 'signal-stop') {
    $Temporary = "$StopPath.$PID.tmp"
    [System.IO.File]::WriteAllText($Temporary, (Get-Date).ToUniversalTime().ToString('o'))
    Move-Item -LiteralPath $Temporary -Destination $StopPath -Force
    $Deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Test-Path -LiteralPath $LockPath) -and (Get-Date) -lt $Deadline) {
        Start-Sleep -Milliseconds 200
    }
    if (Test-Path -LiteralPath $LockPath) { exit 4 }
    Write-Output 'startup-released'
    exit 0
}

if ($Action -eq 'clear-stop') {
    Remove-Item -LiteralPath $StopPath -Force -ErrorAction SilentlyContinue
    exit 0
}

if (Test-Path -LiteralPath $StopPath) { Write-Output 'true'; exit 0 }
Write-Output 'false'
