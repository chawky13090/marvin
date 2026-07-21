[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter()]
    [switch]$Confirmed,

    [Parameter()]
    [string]$ResultPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'data\hyperv-legacy-removal-result.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-IsHyperVOperator {
    if (Test-IsAdministrator) { return $true }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return [bool]($identity.Groups | Where-Object { $_.Value -eq 'S-1-5-32-578' })
}

function Get-PhysicalNetworkState {
    return @(Get-NetAdapter -Physical -ErrorAction SilentlyContinue | ForEach-Object {
        [ordered]@{ name = $_.Name; status = [string]$_.Status; interface_index = $_.ifIndex }
    })
}

if (-not $Confirmed) { throw 'La suppression des anciennes VM doit être confirmée explicitement.' }
if (-not (Test-IsHyperVOperator)) { throw 'Le compte doit être administrateur ou membre du groupe Administrateurs Hyper-V.' }

Import-Module Hyper-V -ErrorAction Stop
$beforeNetwork = Get-PhysicalNetworkState
$inventoryErrors = @()
$allVMs = @(Get-VM -ErrorAction SilentlyContinue -ErrorVariable +inventoryErrors)
$targets = @($allVMs | Where-Object { $_.Name -notlike 'Marvin-*' })
$preserved = @($allVMs | Where-Object { $_.Name -like 'Marvin-*' } | Select-Object -ExpandProperty Name)
$removed = @()
$failed = @()

foreach ($vm in $targets) {
    $diskPaths = @(Get-VMHardDiskDrive -VM $vm -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Path -Unique |
        Where-Object { $_ -and ([IO.Path]::GetExtension($_) -in @('.vhd', '.vhdx', '.avhd', '.avhdx')) })
    try {
        if ($PSCmdlet.ShouldProcess($vm.Name, 'Arrêter, désinscrire et supprimer ses disques virtuels attachés')) {
            if ($vm.State -ne 'Off') { Stop-VM -VM $vm -TurnOff -Force -Confirm:$false }
            Remove-VM -VM $vm -Force -Confirm:$false
            $deletedDisks = @()
            foreach ($disk in $diskPaths) {
                if (Test-Path -LiteralPath $disk -PathType Leaf) {
                    Remove-Item -LiteralPath $disk -Force -Confirm:$false
                    $deletedDisks += $disk
                }
            }
            $removed += [ordered]@{ name = $vm.Name; id = [string]$vm.Id; deleted_disks = $deletedDisks }
        }
    }
    catch {
        $failed += [ordered]@{ name = $vm.Name; id = [string]$vm.Id; error = $_.Exception.Message }
    }
}

$remainingErrors = @()
$remaining = @(Get-VM -ErrorAction SilentlyContinue -ErrorVariable +remainingErrors | Select-Object Name, Id, State)
$result = [ordered]@{
    timestamp = (Get-Date).ToString('o')
    confirmed = $true
    elevated = Test-IsAdministrator
    hyperv_operator = $true
    preserved_marvin_vms = $preserved
    discovered_legacy_vms = @($targets | Select-Object Name, Id, State, Path)
    removed = $removed
    failed = $failed
    inventory_errors_before = @($inventoryErrors | ForEach-Object { $_.Exception.Message } | Select-Object -Unique)
    inventory_errors_after = @($remainingErrors | ForEach-Object { $_.Exception.Message } | Select-Object -Unique)
    remaining_vms = $remaining
    host_network_modified = $false
    physical_network_before = $beforeNetwork
    physical_network_after = Get-PhysicalNetworkState
    status = $(if ($failed.Count) { 'partial_failure' } elseif ($targets.Count -eq 0 -and $inventoryErrors.Count) { 'blocked_corrupt_inventory' } else { 'completed' })
}

$parent = Split-Path $ResultPath -Parent
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$temporary = $ResultPath + '.tmp'
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporary -Encoding UTF8
Move-Item -LiteralPath $temporary -Destination $ResultPath -Force
$result | ConvertTo-Json -Depth 10

if ($result.status -ne 'completed') { exit 2 }
