[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter()]
    [switch]$Confirmed,

    [Parameter()]
    [string]$ResultPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'data\hyperv-orphan-cleanup-result.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

trap {
    $failure = [ordered]@{
        timestamp = (Get-Date).ToString('o')
        status = 'failed'
        error = $_.Exception.Message
        rollback_performed = $(if (Get-Variable rolledBack -ErrorAction SilentlyContinue) { [bool]$rolledBack } else { $false })
        host_network_modified = $false
    }
    $parent = Split-Path $ResultPath -Parent
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $failure | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-PhysicalNetworkState {
    return @(Get-NetAdapter -Physical -ErrorAction SilentlyContinue | ForEach-Object {
        [ordered]@{ name = $_.Name; status = [string]$_.Status; interface_index = $_.ifIndex }
    })
}

function Copy-CacheEntry {
    param([Parameter(Mandatory)][string]$Source, [Parameter(Mandatory)][string]$DestinationRoot)
    New-Item -ItemType Directory -Path $DestinationRoot -Force | Out-Null
    Copy-Item -LiteralPath $Source -Destination $DestinationRoot -Recurse -Force
}

if (-not $Confirmed) { throw 'Le nettoyage du cache Hyper-V doit être confirmé explicitement.' }
if (-not (Test-IsAdministrator)) { throw 'Ce nettoyage du magasin Hyper-V exige une élévation administrateur.' }
$ConfirmPreference = 'None'

Import-Module Hyper-V -ErrorAction Stop
$store = 'C:\ProgramData\Microsoft\Windows\Hyper-V'
$vmCache = Join-Path $store 'Virtual Machines Cache'
$snapshotCache = Join-Path $store 'Snapshots Cache'
$requiredNames = @('Marvin-Windows11-TestForge', 'Marvin-Debian13-TestForge')
$liveVMs = @($requiredNames | ForEach-Object { Get-VM -Name $_ -ErrorAction Stop })
if (@($liveVMs | Where-Object State -ne 'Off').Count -ne 0) {
    throw 'Les deux VM Marvin doivent être arrêtées avant le nettoyage du cache.'
}
$liveIds = @($liveVMs | ForEach-Object { $_.Id.ToString().ToUpperInvariant() })
$checkpointIds = @($liveVMs | ForEach-Object {
    Get-VMCheckpoint -VMName $_.Name -ErrorAction SilentlyContinue | ForEach-Object { $_.Id.ToString().ToUpperInvariant() }
})

$orphanVMFiles = @(Get-ChildItem -LiteralPath $vmCache -Filter '*.vmcx' -File | Where-Object {
    $_.BaseName.ToUpperInvariant() -notin $liveIds
})
$orphanVMDirectories = @(Get-ChildItem -LiteralPath $vmCache -Directory | Where-Object {
    $_.Name.ToUpperInvariant() -notin $liveIds
})
$orphanSnapshotFiles = @(Get-ChildItem -LiteralPath $snapshotCache -Filter '*.vmcx' -File | Where-Object {
    $_.BaseName.ToUpperInvariant() -notin $checkpointIds
})
$orphanSnapshotDirectories = @(Get-ChildItem -LiteralPath $snapshotCache -Directory | Where-Object {
    $_.Name.ToUpperInvariant() -notin $checkpointIds
})

if ($orphanVMFiles.Count -ne 12 -or $orphanVMDirectories.Count -ne 12) {
    throw "Précondition refusée : 12 fichiers et 12 dossiers VM orphelins attendus, observés $($orphanVMFiles.Count)/$($orphanVMDirectories.Count)."
}
if ($orphanSnapshotFiles.Count -ne 13 -or $orphanSnapshotDirectories.Count -ne 13) {
    throw "Précondition refusée : 13 fichiers et 13 dossiers checkpoint orphelins attendus, observés $($orphanSnapshotFiles.Count)/$($orphanSnapshotDirectories.Count)."
}

$projectRoot = Split-Path $PSScriptRoot -Parent
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupRoot = Join-Path $projectRoot ("data\hyperv-store-backup\" + $stamp)
$backupVM = Join-Path $backupRoot 'Virtual Machines Cache'
$backupSnapshots = Join-Path $backupRoot 'Snapshots Cache'
$networkBefore = Get-PhysicalNetworkState
$removedPaths = @()
$rolledBack = $false
$validation = $null

if ($PSCmdlet.ShouldProcess('12 VM fantômes et 13 checkpoints orphelins', 'Sauvegarder puis retirer les entrées cache Hyper-V')) {
    foreach ($item in @($orphanVMFiles) + @($orphanVMDirectories)) { Copy-CacheEntry -Source $item.FullName -DestinationRoot $backupVM }
    foreach ($item in @($orphanSnapshotFiles) + @($orphanSnapshotDirectories)) { Copy-CacheEntry -Source $item.FullName -DestinationRoot $backupSnapshots }
    try {
        Stop-Service -Name vmms -Force -ErrorAction Stop
        foreach ($item in @($orphanVMFiles) + @($orphanVMDirectories) + @($orphanSnapshotFiles) + @($orphanSnapshotDirectories)) {
            Remove-Item -LiteralPath $item.FullName -Recurse -Force -Confirm:$false
            $removedPaths += $item.FullName
        }
    }
    finally {
        Start-Service -Name vmms -ErrorAction Stop
    }
    Start-Sleep -Seconds 3
    $errorsAfter = @()
    $vmsAfter = @(Get-VM -ErrorAction SilentlyContinue -ErrorVariable +errorsAfter)
    $namesAfter = @($vmsAfter | Select-Object -ExpandProperty Name)
    $validation = [ordered]@{
        vm_names = $namesAfter
        errors = @($errorsAfter | ForEach-Object { $_.Exception.Message })
        marvin_preserved = @($requiredNames | Where-Object { $_ -in $namesAfter }).Count -eq 2
    }
    if (-not $validation.marvin_preserved -or $errorsAfter.Count -ne 0) {
        $rolledBack = $true
        Stop-Service -Name vmms -Force -ErrorAction Stop
        try {
            Copy-Item -Path (Join-Path $backupVM '*') -Destination $vmCache -Recurse -Force
            Copy-Item -Path (Join-Path $backupSnapshots '*') -Destination $snapshotCache -Recurse -Force
        }
        finally { Start-Service -Name vmms -ErrorAction Stop }
        throw 'Validation Hyper-V échouée après nettoyage; cache restauré automatiquement.'
    }
}

$result = [ordered]@{
    timestamp = (Get-Date).ToString('o')
    status = 'completed'
    backup_root = $backupRoot
    preserved_vm_ids = $liveIds
    removed_vm_cache_entries = $orphanVMFiles.Count
    removed_snapshot_cache_entries = $orphanSnapshotFiles.Count
    removed_paths = $removedPaths
    validation = $validation
    rollback_performed = $rolledBack
    host_network_modified = $false
    physical_network_before = $networkBefore
    physical_network_after = Get-PhysicalNetworkState
}
$parent = Split-Path $ResultPath -Parent
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$temporary = $ResultPath + '.tmp'
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporary -Encoding UTF8
Move-Item -LiteralPath $temporary -Destination $ResultPath -Force
$result | ConvertTo-Json -Depth 10
