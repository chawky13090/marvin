[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Principal,

    [Parameter(Mandatory = $true)]
    [switch]$Confirmed
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$resultPath = Join-Path $root 'data\hyperv-access-result.json'

trap {
    $failure = [ordered]@{
        timestamp = [DateTimeOffset]::Now.ToString('o')
        principal = $Principal
        membership_verified = $false
        host_network_modified = $false
        error = $_.Exception.Message
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $resultPath) -Force | Out-Null
    $failure | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 1
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principalObject = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principalObject.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not $Confirmed) {
    throw 'La modification exige -Confirmed.'
}
if (-not (Test-IsAdministrator)) {
    throw 'Ce script doit etre execute dans une console elevee.'
}

$groupSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-578')
$groupName = $groupSid.Translate([Security.Principal.NTAccount]).Value.Split('\')[-1]
$target = [Security.Principal.NTAccount]::new($Principal)
$targetSid = $target.Translate([Security.Principal.SecurityIdentifier])
$resolvedTarget = $targetSid.Translate([Security.Principal.NTAccount]).Value
$machinePrefix = $env:COMPUTERNAME + '\'

if (-not $resolvedTarget.StartsWith($machinePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Le compte cible doit etre un compte local de $env:COMPUTERNAME."
}

$networkBefore = @(Get-NetAdapter -Physical -ErrorAction SilentlyContinue | ForEach-Object {
    [ordered]@{ name = $_.Name; status = [string]$_.Status; interface_index = $_.ifIndex }
})
$members = @(Get-LocalGroupMember -Group $groupName -ErrorAction Stop)
$alreadyMember = [bool]($members | Where-Object { $_.SID.Value -eq $targetSid.Value })
$added = $false

if (-not $alreadyMember -and $PSCmdlet.ShouldProcess($resolvedTarget, "Ajouter au groupe local $groupName")) {
    Add-LocalGroupMember -Group $groupName -Member $resolvedTarget -ErrorAction Stop
    $added = $true
}

$membersAfter = @(Get-LocalGroupMember -Group $groupName -ErrorAction Stop)
$membershipVerified = [bool]($membersAfter | Where-Object { $_.SID.Value -eq $targetSid.Value })
$networkAfter = @(Get-NetAdapter -Physical -ErrorAction SilentlyContinue | ForEach-Object {
    [ordered]@{ name = $_.Name; status = [string]$_.Status; interface_index = $_.ifIndex }
})

$result = [ordered]@{
    timestamp = [DateTimeOffset]::Now.ToString('o')
    principal = $resolvedTarget
    principal_sid = $targetSid.Value
    group = $groupName
    added = $added
    membership_verified = $membershipVerified
    host_network_modified = $false
    physical_network_before = $networkBefore
    physical_network_after = $networkAfter
    session_refresh_required = $added
}

$resultDirectory = Split-Path -Parent $resultPath
New-Item -ItemType Directory -Path $resultDirectory -Force | Out-Null
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resultPath -Encoding UTF8
$result | ConvertTo-Json -Depth 6

if (-not $membershipVerified) {
    exit 2
}
