[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [switch]$RemoveData,
    [switch]$KeepSearXngContainer
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Marker = Join-Path $ProjectRoot 'runtime\install\state.json'
$PackageMetadata = Join-Path $ProjectRoot 'runtime\install\package.json'
$LocalAppData = [IO.Path]::GetFullPath([Environment]::GetFolderPath('LocalApplicationData'))
if (-not (Test-Path -LiteralPath $Marker -PathType Leaf)) { throw 'Marqueur d installation Marvin absent; suppression automatique refusee.' }
if ($ProjectRoot -eq [IO.Path]::GetPathRoot($ProjectRoot) -or $ProjectRoot.Length -lt ($LocalAppData.Length + 4)) {
    throw 'Racine Marvin dangereuse; suppression refusee.'
}

if (-not $PSCmdlet.ShouldProcess($ProjectRoot, $(if ($RemoveData) { 'Desinstaller Marvin et supprimer ses donnees' } else { 'Desinstaller Marvin et preserver ses donnees' }))) { exit 0 }

$Stop = Join-Path $PSScriptRoot 'stop-marvin.ps1'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Stop -AllowActiveWorkInterruption
if ($LASTEXITCODE -ne 0) { throw 'Marvin ne peut pas etre arrete proprement.' }

$ProtectedProcessIds = [Collections.Generic.HashSet[int]]::new()
$CurrentProcessId = [int]$PID
while ($CurrentProcessId -gt 0 -and $ProtectedProcessIds.Add($CurrentProcessId)) {
    $CurrentProcess = Get-CimInstance Win32_Process -Filter ("ProcessId = $CurrentProcessId") -ErrorAction SilentlyContinue
    if ($null -eq $CurrentProcess) { break }
    $CurrentProcessId = [int]$CurrentProcess.ParentProcessId
}
$ResidualProcessIds = @()
foreach ($Process in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
    if ($ProtectedProcessIds.Contains([int]$Process.ProcessId)) { continue }
    $CommandLine = [string]$Process.CommandLine
    if ($CommandLine.IndexOf($ProjectRoot, [StringComparison]::OrdinalIgnoreCase) -lt 0) { continue }
    & taskkill.exe /PID ([int]$Process.ProcessId) /T /F 2>$null | Out-Null
    $ResidualProcessIds += [int]$Process.ProcessId
}

Unregister-ScheduledTask -TaskName 'Marvin - Demarrage automatique' -Confirm:$false -ErrorAction SilentlyContinue
foreach ($Name in @('Marvin - Frontend', 'Marvin - Backend', 'Marvin - HTTPS')) {
    Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
}
if (-not $KeepSearXngContainer -and (Get-Command docker.exe -ErrorAction SilentlyContinue)) {
    & docker.exe rm -f marvin-searxng 2>$null | Out-Null
}
foreach ($Shortcut in @('Marvin.lnk', 'Desinstaller Marvin.lnk')) {
    Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)) $Shortcut) -Force -ErrorAction SilentlyContinue
}

$PreservedData = $null
if (-not $RemoveData -and (Test-Path -LiteralPath (Join-Path $ProjectRoot 'data') -PathType Container)) {
    $PreserveRoot = Join-Path $LocalAppData 'Marvin\PreservedData'
    New-Item -ItemType Directory -Path $PreserveRoot -Force | Out-Null
    $PreservedData = Join-Path $PreserveRoot (Get-Date -Format 'yyyyMMdd-HHmmss')
    Move-Item -LiteralPath (Join-Path $ProjectRoot 'data') -Destination $PreservedData
}

$RollbackPath = $null
if (Test-Path -LiteralPath $PackageMetadata -PathType Leaf) {
    try {
        $Candidate = [string]((Get-Content -LiteralPath $PackageMetadata -Raw | ConvertFrom-Json).rollback_path)
        if (-not [string]::IsNullOrWhiteSpace($Candidate)) {
            $Candidate = [IO.Path]::GetFullPath($Candidate)
            $ExpectedParent = [IO.Path]::GetFullPath((Split-Path -Parent $ProjectRoot))
            $CandidateParent = [IO.Path]::GetFullPath((Split-Path -Parent $Candidate))
            $CandidateName = [IO.Path]::GetFileName($Candidate)
            if ($CandidateParent -eq $ExpectedParent -and $CandidateName -match '^Marvin\.rollback-\d{14}$') {
                $RollbackPath = $Candidate
            }
        }
    } catch { $RollbackPath = $null }
}

$CleanupScript = Join-Path $env:TEMP ("marvin-uninstall-$PID.ps1")
$ReceiptRoot = Join-Path $LocalAppData 'Marvin\UninstallReceipts'
New-Item -ItemType Directory -Path $ReceiptRoot -Force | Out-Null
$ReceiptPath = Join-Path $ReceiptRoot ("uninstall-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + "-$PID.json")
$QuotedRoot = $ProjectRoot.Replace("'", "''")
$QuotedRollback = if ($RollbackPath) { $RollbackPath.Replace("'", "''") } else { '' }
$QuotedReceipt = $ReceiptPath.Replace("'", "''")
$Cleanup = @"
Start-Sleep -Seconds 3
`$Target = [IO.Path]::GetFullPath('$QuotedRoot')
if (`$Target -eq [IO.Path]::GetPathRoot(`$Target) -or `$Target.Length -lt 12) { exit 2 }
`$Rollback = '$QuotedRollback'
`$Receipt = '$QuotedReceipt'
`$RemovalErrors = [ordered]@{}
function Remove-Bounded([string]`$Path) {
    if ([string]::IsNullOrWhiteSpace(`$Path)) { return `$true }
    `$LastError = ''
    for (`$Attempt = 1; `$Attempt -le 5; `$Attempt++) {
        try { Remove-Item -LiteralPath `$Path -Recurse -Force -ErrorAction Stop } catch { `$LastError = `$_.Exception.Message }
        if (Test-Path -LiteralPath `$Path -PathType Container) {
            try { [IO.Directory]::Delete(`$Path, `$true) } catch { `$LastError = `$_.Exception.Message }
        }
        if (-not (Test-Path -LiteralPath `$Path)) { return `$true }
        Start-Sleep -Seconds 2
    }
    `$RemovalErrors[`$Path] = `$LastError
    return `$false
}
`$TargetRemoved = Remove-Bounded `$Target
`$RollbackRemoved = Remove-Bounded `$Rollback
`$Result = [ordered]@{
    schema_version = 1
    completed_at = [DateTime]::UtcNow.ToString('o')
    success = [bool](`$TargetRemoved -and `$RollbackRemoved)
    target_removed = [bool]`$TargetRemoved
    rollback_removed = [bool]`$RollbackRemoved
    removal_errors = `$RemovalErrors
}
[IO.File]::WriteAllText(`$Receipt, (`$Result | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new(`$false))
Remove-Item -LiteralPath `$MyInvocation.MyCommand.Path -Force
"@
[IO.File]::WriteAllText($CleanupScript, $Cleanup, [Text.UTF8Encoding]::new($false))
Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $CleanupScript) -WindowStyle Hidden | Out-Null

[ordered]@{
    success = $true
    removal_scheduled = $true
    data_removed = [bool]$RemoveData
    preserved_data = $PreservedData
    rollback_scheduled_for_removal = $RollbackPath
    residual_process_ids_stopped = @($ResidualProcessIds)
    completion_receipt = $ReceiptPath
    completion_pending = $true
    shared_system_runtimes_removed = $false
} | ConvertTo-Json -Depth 5
