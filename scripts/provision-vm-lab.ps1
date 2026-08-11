[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter()]
    [ValidateSet('Windows11', 'Debian13', 'Both')]
    [string]$Profile = 'Both',

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$MachineRoot = (Join-Path $env:LOCALAPPDATA 'Marvin'),

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$SwitchName = 'Default Switch',

    [Parameter()]
    [switch]$StartAfterCreate
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

function Resolve-LocalFixedRoot {
    param([Parameter(Mandatory)][string]$Path)
    $expanded = [Environment]::ExpandEnvironmentVariables($Path)
    $full = [IO.Path]::GetFullPath($expanded)
    $root = [IO.Path]::GetPathRoot($full)
    $drive = Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='" + $root.TrimEnd('\') + "'")
    if (-not $drive -or $drive.DriveType -ne 3) {
        throw "La bibliothèque VM exige un disque local fixe : $full"
    }
    return $full.TrimEnd('\')
}

function New-MarvinLabVM {
    param([Parameter(Mandatory)][hashtable]$Definition)

    $existing = Get-VM -Name $Definition.Name -ErrorAction SilentlyContinue
    if ($existing) {
        return [ordered]@{ name = $Definition.Name; action = 'existing_preserved'; state = [string]$existing.State }
    }
    if (-not (Test-Path -LiteralPath $Definition.Iso -PathType Leaf)) {
        throw "ISO absente : $($Definition.Iso)"
    }
    $observed = (Get-FileHash -Algorithm $Definition.HashAlgorithm -LiteralPath $Definition.Iso).Hash
    if ($observed -ne $Definition.ExpectedHash) {
        throw "Empreinte invalide pour $($Definition.Iso). Création refusée."
    }
    $drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($Definition.Path).TrimEnd(':\'))
    if ($drive.Free -lt $Definition.MinimumFreeBytes) {
        throw "Espace libre insuffisant pour $($Definition.Name)."
    }
    if (-not $PSCmdlet.ShouldProcess($Definition.Name, 'Créer une VM Hyper-V Marvin Generation 2')) {
        return [ordered]@{ name = $Definition.Name; action = 'whatif_or_declined' }
    }

    New-Item -ItemType Directory -Path $Definition.Path -Force | Out-Null
    $vhd = Join-Path $Definition.Path ($Definition.Name + '.vhdx')
    $created = $false
    try {
        $vm = New-VM -Name $Definition.Name -Generation 2 -Path $Definition.Path `
            -MemoryStartupBytes $Definition.MemoryBytes -NewVHDPath $vhd `
            -NewVHDSizeBytes $Definition.DiskBytes -SwitchName $SwitchName
        $created = $true
        Set-VM -VM $vm -ProcessorCount $Definition.Processors -DynamicMemory `
            -MemoryMinimumBytes $Definition.MemoryMinimumBytes `
            -MemoryMaximumBytes $Definition.MemoryMaximumBytes `
            -AutomaticCheckpointsEnabled $false -CheckpointType ProductionOnly
        $dvd = Add-VMDvdDrive -VMName $Definition.Name -Path $Definition.Iso -Passthru
        Set-VMFirmware -VMName $Definition.Name -EnableSecureBoot On `
            -SecureBootTemplate $Definition.SecureBootTemplate -FirstBootDevice $dvd
        if ($Definition.EnableTPM) {
            Set-VMKeyProtector -VMName $Definition.Name -NewLocalKeyProtector
            Enable-VMTPM -VMName $Definition.Name
        }
        if ($StartAfterCreate) { Start-VM -Name $Definition.Name | Out-Null }
        return [ordered]@{
            name = $Definition.Name; action = 'created'; generation = 2
            path = $Definition.Path; vhd = $vhd; iso = $Definition.Iso
            secure_boot_template = $Definition.SecureBootTemplate
            vtpm = [bool]$Definition.EnableTPM; started = [bool]$StartAfterCreate
        }
    }
    catch {
        if ($created) {
            Stop-VM -Name $Definition.Name -TurnOff -Force -ErrorAction SilentlyContinue
            Remove-VM -Name $Definition.Name -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}

if (-not (Test-IsHyperVOperator)) {
    throw 'Le compte doit être administrateur ou membre du groupe Administrateurs Hyper-V.'
}

Import-Module Hyper-V -ErrorAction Stop
$root = Resolve-LocalFixedRoot -Path $MachineRoot
$null = Get-VMSwitch -Name $SwitchName -ErrorAction Stop

$definitions = @{
    Windows11 = @{
        Name = 'Marvin-Windows11-TestForge'
        Path = Join-Path $root 'library\vm\windows\Marvin-Windows11-TestForge'
        Iso = Join-Path $root 'library\iso\windows\Win11_25H2_French_x64_v2.iso'
        HashAlgorithm = 'SHA256'
        ExpectedHash = 'A02693BEB8EB166AFDFDB7DB49176A2B547F81E61030A695FE172277DB6A1977'
        MemoryBytes = 4GB; MemoryMinimumBytes = 3GB; MemoryMaximumBytes = 6GB; DiskBytes = 80GB; MinimumFreeBytes = 80GB; Processors = 4
        SecureBootTemplate = 'MicrosoftWindows'; EnableTPM = $true
    }
    Debian13 = @{
        Name = 'Marvin-Debian13-TestForge'
        Path = Join-Path $root 'library\vm\linux\Marvin-Debian13-TestForge'
        Iso = Join-Path $root 'library\iso\linux\debian-13.6.0-amd64-netinst.iso'
        HashAlgorithm = 'SHA512'
        ExpectedHash = 'CE0EEEE7B51FDCDBED1E5116668C1FEE27E528767BDF488E5F115A67B225E5DFD0AFCA1D456AAA9408CEB6B8527521FF7B6B5D62FDBE6F8C5FAAF8DF56A96292'
        MemoryBytes = 4GB; MemoryMinimumBytes = 2GB; MemoryMaximumBytes = 4GB; DiskBytes = 40GB; MinimumFreeBytes = 25GB; Processors = 4
        SecureBootTemplate = 'MicrosoftUEFICertificateAuthority'; EnableTPM = $false
    }
}

$selected = if ($Profile -eq 'Both') { @('Windows11', 'Debian13') } else { @($Profile) }
$results = @()
foreach ($item in $selected) {
    $results += New-MarvinLabVM -Definition $definitions[$item]
}

[ordered]@{
    timestamp = (Get-Date).ToString('o')
    machine_root = $root
    switch = $SwitchName
    host_network_modified = $false
    results = $results
} | ConvertTo-Json -Depth 8
