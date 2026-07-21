[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('debian13', 'windows11')]
    [string]$Profile,

    [Parameter(Mandatory)]
    [switch]$Confirmed,

    [ValidateNotNullOrEmpty()]
    [string]$MachineRoot = (Join-Path $env:LOCALAPPDATA 'Marvin')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $Confirmed) { throw 'La recréation de la VM doit être confirmée explicitement.' }

$root = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($MachineRoot)).TrimEnd('\')
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'

if ($Profile -eq 'debian13') {
    $seed = Join-Path $root 'library\vm\seeds\debian13'
    $source = Join-Path $root 'library\iso\linux\debian-13.6.0-amd64-netinst.iso'
    $preseed = Join-Path $seed 'preseed.cfg'
    $unattended = Join-Path $seed 'debian-13.6.0-marvin-unattended.iso'
    New-Item -ItemType Directory -Path $seed -Force | Out-Null
    & $python (Join-Path $PSScriptRoot 'prepare-vm-unattended.py') debian13 --output $seed | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'La préparation Debian sans assistance a échoué.' }
    & (Join-Path $PSScriptRoot 'build-debian-unattended-iso.ps1') -SourceIso $source -Preseed $preseed -OutputIso $unattended
    if ($LASTEXITCODE -ne 0) { throw 'La construction du média Debian sans assistance a échoué.' }
    & (Join-Path $PSScriptRoot 'install-debian-vm-lab.ps1') -MachineRoot $root -Confirm:$false
    if ($LASTEXITCODE -ne 0) { throw 'L installation Debian Test Forge a échoué.' }
    return
}

& (Join-Path $PSScriptRoot 'install-windows-vm-lab.ps1') -MachineRoot $root -Confirm:$false
if ($LASTEXITCODE -ne 0) { throw 'L installation Windows Test Forge a échoué.' }
