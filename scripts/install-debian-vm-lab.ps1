[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$MachineRoot = (Join-Path $env:LOCALAPPDATA 'Marvin'),

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$SwitchName = 'Default Switch',

    [Parameter()]
    [ValidateRange(10, 90)]
    [int]$TimeoutMinutes = 45
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$vmName = 'Marvin-Debian13-TestForge'
$checkpointName = 'Marvin-Clean'
$root = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($MachineRoot)).TrimEnd('\')
$vmDirectory = Join-Path $root 'library\vm\linux\Marvin-Debian13-TestForge'
$seedDirectory = Join-Path $root 'library\vm\seeds\debian13'
$sourceIso = Join-Path $root 'library\iso\linux\debian-13.6.0-amd64-netinst.iso'
$unattendedIso = Join-Path $seedDirectory 'debian-13.6.0-marvin-unattended.iso'
$resultPath = Join-Path $PSScriptRoot '..\data\debian-vm-install-result.json'
$python = Join-Path $PSScriptRoot '..\backend\.venv\Scripts\python.exe'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$privateKeySecret = 'vm_lab.debian13.ssh_private_key'

function Assert-ChildPath {
    param([Parameter(Mandatory)][string]$Parent, [Parameter(Mandatory)][string]$Child)
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $childFull = [IO.Path]::GetFullPath($Child)
    if (-not $childFull.StartsWith($parentFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Chemin hors périmètre refusé : $childFull"
    }
}

function Write-Result {
    param([Parameter(Mandatory)][hashtable]$Value)
    $Value.timestamp = (Get-Date).ToString('o')
    $parent = Split-Path -Parent $resultPath
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temporaryResult = $resultPath + '.tmp'
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporaryResult -Encoding UTF8
    Move-Item -LiteralPath $temporaryResult -Destination $resultPath -Force
}

Assert-ChildPath -Parent $root -Child $vmDirectory
Assert-ChildPath -Parent $root -Child $seedDirectory
if (-not (Test-Path -LiteralPath $unattendedIso -PathType Leaf)) { throw "Média Debian automatisé absent : $unattendedIso" }
if (-not (Test-Path -LiteralPath $sourceIso -PathType Leaf)) { throw "ISO Debian source absente : $sourceIso" }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Runtime Python Marvin absent : $python" }
Import-Module Hyper-V -ErrorAction Stop
$null = Get-VMSwitch -Name $SwitchName -ErrorAction Stop

if (-not $PSCmdlet.ShouldProcess($vmName, 'Recréer et installer Debian 13 sans assistance')) {
    Write-Result @{ status = 'declined'; vm_name = $vmName }
    return
}

$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ('marvin-debian-install-' + [guid]::NewGuid().ToString('N'))
$keyPath = Join-Path $temporaryRoot 'id_ed25519'
$knownHosts = Join-Path $temporaryRoot 'known_hosts'
$created = $false
try {
    $existing = Get-VM -Name $vmName -ErrorAction SilentlyContinue
    if ($existing) {
        if ($existing.State -ne 'Off') { Stop-VM -VM $existing -TurnOff -Force }
        Remove-VM -VM $existing -Force
    }
    if (Test-Path -LiteralPath $vmDirectory) { Remove-Item -LiteralPath $vmDirectory -Recurse -Force }
    New-Item -ItemType Directory -Path $vmDirectory -Force | Out-Null
    $vhd = Join-Path $vmDirectory ($vmName + '.vhdx')
    $vm = New-VM -Name $vmName -Generation 2 -Path $vmDirectory -MemoryStartupBytes 4GB `
        -NewVHDPath $vhd -NewVHDSizeBytes 40GB -SwitchName $SwitchName
    $created = $true
    Set-VM -VM $vm -ProcessorCount 4 -DynamicMemory -MemoryMinimumBytes 2GB `
        -MemoryMaximumBytes 4GB -AutomaticCheckpointsEnabled $false -CheckpointType ProductionOnly
    $dvd = Add-VMDvdDrive -VMName $vmName -Path $unattendedIso -Passthru
    Set-VMFirmware -VMName $vmName -EnableSecureBoot On `
        -SecureBootTemplate MicrosoftUEFICertificateAuthority -FirstBootDevice $dvd
    Start-VM -VM $vm | Out-Null

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $ip = $null
    do {
        Start-Sleep -Seconds 10
        $addresses = @(Get-VMNetworkAdapter -VMName $vmName | ForEach-Object IPAddresses)
        $ip = $addresses | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' -and $_ -notlike '169.254.*' } | Select-Object -First 1
        if ($ip -and (Test-NetConnection -ComputerName $ip -Port 22 -InformationLevel Quiet -WarningAction SilentlyContinue)) { break }
        $state = Get-VM -Name $vmName
        if ($state.State -eq 'Off') { throw 'La VM Debian s est arrêtée avant que SSH soit disponible.' }
    } while ((Get-Date) -lt $deadline)
    if (-not $ip) { throw "Debian n a pas exposé SSH avant le délai de $TimeoutMinutes minutes." }

    New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
    & icacls.exe $temporaryRoot /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" | Out-Null
    & $python (Join-Path $PSScriptRoot 'materialize-vm-secret.py') --key $privateKeySecret --output $keyPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'La clé SSH DPAPI n a pas pu être matérialisée.' }
    & icacls.exe $keyPath /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null

    $sshArgs = @('-i', $keyPath, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'StrictHostKeyChecking=accept-new', '-o', "UserKnownHostsFile=$knownHosts")
    $evidence = & ssh.exe @sshArgs "marvin@$ip" 'printf "user=%s\n" "$(id -un)"; printf "os="; . /etc/os-release; printf "%s %s\n" "$ID" "$VERSION_ID"; printf "python="; python3 --version; printf "shellcheck="; shellcheck --version | head -n 1; printf "bats="; bats --version; printf "native_runner="; sudo /usr/local/sbin/marvin-test-forge-runner --version; systemctl is-enabled ssh'
    if ($LASTEXITCODE -ne 0 -or ($evidence -join "`n") -notmatch 'user=marvin') { throw 'La validation SSH Debian a échoué.' }
    & ssh.exe @sshArgs "marvin@$ip" 'sudo /usr/bin/systemctl poweroff' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'L arrêt propre de Debian a échoué.' }
    $poweroffDeadline = (Get-Date).AddMinutes(3)
    do { Start-Sleep -Seconds 3; $vm = Get-VM -Name $vmName } while ($vm.State -ne 'Off' -and (Get-Date) -lt $poweroffDeadline)
    if ($vm.State -ne 'Off') { throw 'Debian ne s est pas arrêtée proprement.' }
    Get-VMDvdDrive -VMName $vmName | Set-VMDvdDrive -Path $null
    $disk = Get-VMHardDiskDrive -VMName $vmName | Select-Object -First 1
    Set-VMFirmware -VMName $vmName -FirstBootDevice $disk
    Checkpoint-VM -Name $vmName -SnapshotName $checkpointName | Out-Null
    Write-Result @{
        status = 'completed'; vm_name = $vmName; checkpoint = $checkpointName; ip_during_install = $ip
        username = 'marvin'; authentication = 'ssh_ed25519_dpapi'; guest_password_enabled = $false
        native_runner_version = 1
        host_network_modified = $false; guest_network_connected_during_install = $true
        evidence = @($evidence); unattended_iso_sha512 = (Get-FileHash -Algorithm SHA512 -LiteralPath $unattendedIso).Hash
    }
    Get-Content -LiteralPath $resultPath -Raw
}
catch {
    if ($created) {
        $failed = Get-VM -Name $vmName -ErrorAction SilentlyContinue
        if ($failed -and $failed.State -ne 'Off') { Stop-VM -VM $failed -TurnOff -Force -ErrorAction SilentlyContinue }
    }
    Write-Result @{ status = 'failed'; vm_name = $vmName; error = $_.Exception.Message; host_network_modified = $false }
    throw
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        & icacls.exe $temporaryRoot /grant:r "${env:USERNAME}:(OI)(CI)F" /T /C | Out-Null
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
