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

function Test-UninstallContainerOwnership([object[]]$Mounts, [string]$Root) {
    $Prefix = $Root.TrimEnd('\') + '\'
    foreach ($Mount in $Mounts) {
        if ([string]$Mount.Type -ne 'bind') { continue }
        $Source = [string]$Mount.Source
        if ($Source.Equals($Root,[StringComparison]::OrdinalIgnoreCase) -or $Source.StartsWith($Prefix,[StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

function Read-UninstallContainerInspection([string]$Output) {
    $Parts=$Output.Trim() -split '\|',2
    if($Parts.Count -ne 2 -or $Parts[0] -notmatch '^[a-f0-9]{64}$') { throw 'Identite de conteneur non confirmee.' }
    # Windows PowerShell 5.1 emet le tableau JSON comme un objet unique dans
    # un pipeline. L'affectation puis le cast evitent un tableau imbrique.
    $Mounts=ConvertFrom-Json -InputObject $Parts[1]
    return [pscustomobject]@{id=$Parts[0];mounts=[object[]]$Mounts}
}

function Invoke-UninstallDocker([string[]]$Arguments) {
    $Docker=Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
    $Out=[IO.Path]::GetTempFileName();$Err=[IO.Path]::GetTempFileName();$Process=$null
    try {
        $Process=Start-Process $Docker -ArgumentList (@('--host','npipe:////./pipe/dockerDesktopLinuxEngine')+$Arguments) -PassThru -WindowStyle Hidden -RedirectStandardOutput $Out -RedirectStandardError $Err
        $null=$Process.Handle
        if(-not $Process.WaitForExit(30000)){
            & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
            throw 'Operation Docker non confirmee; desinstallation suspendue sans suppression de donnees.'
        }
        $Process.WaitForExit()
        return [pscustomobject]@{exit_code=[int]$Process.ExitCode;output=[IO.File]::ReadAllText($Out);error=[IO.File]::ReadAllText($Err)}
    } finally {
        if($Process){$Process.Dispose()}
        Remove-Item -LiteralPath $Out,$Err -Force
    }
}

function Test-UninstallProcessIdentity([object]$Snapshot, [object]$Current) {
    return $null -ne $Current -and
        [int]$Snapshot.ProcessId -eq [int]$Current.ProcessId -and
        $Snapshot.CreationDate -eq $Current.CreationDate
}

function Stop-UninstallProcessSnapshot([object]$Snapshot) {
    $ProcessId=[int]$Snapshot.ProcessId
    $Current=Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
    if(-not (Test-UninstallProcessIdentity $Snapshot $Current)){return $false}
    $Out=[IO.Path]::GetTempFileName();$Err=[IO.Path]::GetTempFileName();$Killer=$null
    try {
        $Killer=Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\taskkill.exe') -ArgumentList @('/PID',[string]$ProcessId,'/T','/F') -WindowStyle Hidden -PassThru -RedirectStandardOutput $Out -RedirectStandardError $Err
        $null=$Killer.Handle
        if(-not $Killer.WaitForExit(10000)){throw 'Arret de processus non confirme dans le delai; suppression suspendue.'}
        $Killer.WaitForExit()
        $After=Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
        # Un parent peut avoir deja termine cet enfant. La postcondition compte,
        # pas le stderr de taskkill; un PID reutilise ne doit jamais etre retue.
        if(Test-UninstallProcessIdentity $Snapshot $After){throw 'Processus Marvin encore actif; suppression suspendue.'}
        return $true
    } finally {
        if($Killer){$Killer.Dispose()}
        Remove-Item -LiteralPath $Out,$Err -Force -ErrorAction SilentlyContinue
    }
}
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
    if(Stop-UninstallProcessSnapshot $Process){$ResidualProcessIds += [int]$Process.ProcessId}
}

Unregister-ScheduledTask -TaskName 'Marvin - Demarrage automatique' -Confirm:$false -ErrorAction SilentlyContinue
foreach ($Name in @('Marvin - Frontend', 'Marvin - Backend', 'Marvin - HTTPS')) {
    Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
}
if (-not $KeepSearXngContainer -and (Test-Path (Join-Path $ProjectRoot 'docker\searxng\settings.yml')) -and
    (Test-Path (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'))) {
    $Inspection=Invoke-UninstallDocker @('inspect','--format','"{{.Id}}|{{json .Mounts}}"','marvin-searxng')
    if ($Inspection.exit_code -ne 0 -and $Inspection.error -notmatch '(?i)no such (object|container).*marvin-searxng') {
        throw 'Inspection Docker non confirmee; verifier le moteur avant de desinstaller.'
    }
    if ($Inspection.exit_code -eq 0 -and [string]::IsNullOrWhiteSpace($Inspection.output)) {
        throw 'Inspection Docker vide; aucune absence de conteneur supposee.'
    }
    if ($Inspection.exit_code -eq 0) {
        $Container=Read-UninstallContainerInspection $Inspection.output
        if (Test-UninstallContainerOwnership $Container.mounts $ProjectRoot) {
            $Removed=Invoke-UninstallDocker @('rm','-f',$Container.id)
            if($Removed.exit_code -ne 0){throw 'Conteneur gere non retire; desinstallation interrompue sans suppression de donnees.'}
        }
    }
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
