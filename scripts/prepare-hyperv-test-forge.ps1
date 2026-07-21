[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$VMName,

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$CheckpointName = 'Marvin-Clean',

    [Parameter()]
    [switch]$GrantCurrentUser,

    [Parameter()]
    [switch]$CreateCheckpoint
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-HyperVAdministratorsGroup {
    $sid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-578')
    return $sid.Translate([Security.Principal.NTAccount]).Value.Split('\')[-1]
}

$result = [ordered]@{
    computer = $env:COMPUTERNAME
    user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    elevated = Test-IsAdministrator
    features = @()
    services = @()
    hyperv_module = [bool](Get-Module -ListAvailable -Name Hyper-V)
    hyperv_firewall = [bool](Get-Command New-NetFirewallHyperVRule -ErrorAction SilentlyContinue)
    vm = $null
    checkpoint = $null
    membership = $false
    actions = @()
}

foreach ($featureName in @('Microsoft-Hyper-V-All', 'Containers-DisposableClientVM')) {
    try {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName $featureName
        $result.features += [ordered]@{ name = $featureName; state = [string]$feature.State }
    }
    catch {
        $result.features += [ordered]@{ name = $featureName; state = 'unknown'; error = $_.Exception.Message }
    }
}

foreach ($serviceName in @('vmms', 'HvHost')) {
    $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    $result.services += [ordered]@{
        name = $serviceName
        status = $(if ($service) { [string]$service.Status } else { 'missing' })
        start_type = $(if ($service) { [string]$service.StartType } else { 'missing' })
    }
}

$groupName = Get-HyperVAdministratorsGroup
$members = @(Get-LocalGroupMember -Group $groupName -ErrorAction SilentlyContinue)
$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$result.membership = [bool]($members | Where-Object SID -eq $currentSid)

if ($GrantCurrentUser -and -not $result.membership) {
    if (-not $result.elevated) {
        throw 'Exécutez PowerShell en administrateur pour accorder le rôle Hyper-V.'
    }
    if ($PSCmdlet.ShouldProcess($result.user, "Ajouter au groupe local $groupName")) {
        Add-LocalGroupMember -Group $groupName -Member $result.user
        $result.actions += 'current_user_added_to_hyperv_administrators'
        $result.membership = $true
    }
}

if ($VMName) {
    try {
        $vm = Get-VM -Name $VMName -ErrorAction Stop
        $result.vm = [ordered]@{
            name = $vm.Name; state = [string]$vm.State; generation = $vm.Generation
            checkpoint_type = [string]$vm.CheckpointType
        }
        $checkpoint = Get-VMCheckpoint -VMName $VMName -Name $CheckpointName -ErrorAction SilentlyContinue
        if ($checkpoint) {
            $result.checkpoint = [ordered]@{ name = $checkpoint.Name; created = $checkpoint.CreationTime }
        }
        elseif ($CreateCheckpoint) {
            if (-not $result.elevated) {
                throw 'Exécutez PowerShell en administrateur pour créer le checkpoint.'
            }
            if ($vm.State -ne 'Off') {
                throw 'La VM doit être arrêtée avant de créer le checkpoint de référence.'
            }
            if ($PSCmdlet.ShouldProcess($VMName, "Créer le checkpoint $CheckpointName")) {
                Set-VM -Name $VMName -CheckpointType ProductionOnly
                Checkpoint-VM -Name $VMName -SnapshotName $CheckpointName
                $result.actions += 'production_checkpoint_created'
                $result.checkpoint = [ordered]@{ name = $CheckpointName; created = (Get-Date) }
            }
        }
    }
    catch {
        $result.vm = [ordered]@{ name = $VMName; error = $_.Exception.Message }
    }
}

$result | ConvertTo-Json -Depth 8

if ($GrantCurrentUser -and $result.actions -contains 'current_user_added_to_hyperv_administrators') {
    Write-Warning 'Fermez puis rouvrez la session Windows avant de relancer Marvin.'
}
