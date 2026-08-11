[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [ValidateNotNullOrEmpty()]
    [string]$MachineRoot = (Join-Path $env:LOCALAPPDATA 'Marvin'),

    [ValidateNotNullOrEmpty()]
    [string]$SwitchName = 'Default Switch',

    [ValidateRange(30, 120)]
    [int]$TimeoutMinutes = 90
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$vmName = 'Marvin-Windows11-TestForge'
$root = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($MachineRoot)).TrimEnd('\')
$vmDirectory = Join-Path $root 'library\vm\windows\Marvin-Windows11-TestForge'
$seedDirectory = Join-Path $root 'library\vm\seeds\windows11'
$sourceIso = Join-Path $root 'library\iso\windows\Win11_25H2_French_x64_v2.iso'
$seedIso = Join-Path $seedDirectory 'windows11-marvin-autounattend.iso'
$answerFile = Join-Path $seedDirectory 'Autounattend.xml'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$resultPath = Join-Path $projectRoot 'data\windows-vm-install-result.json'
$provisionResultPath = Join-Path $projectRoot 'data\windows-vm-provision-result.json'
$secretPath = Join-Path $projectRoot 'data\.windows-vm-install-secret.txt'
$expectedIsoHash = 'A02693BEB8EB166AFDFDB7DB49176A2B547F81E61030A695FE172277DB6A1977'
$session = $null
$password = $null
$created = $false

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
    $temporary = $resultPath + '.tmp'
    $Value | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $resultPath -Force
}

function New-GuestSession {
    param([Parameter(Mandatory)][PSCredential]$Credential, [Parameter(Mandatory)][datetime]$Deadline)
    do {
        try { return New-PSSession -VMName $vmName -Credential $Credential -ErrorAction Stop }
        catch { Start-Sleep -Seconds 10 }
        $state = Get-VM -Name $vmName -ErrorAction Stop
        if ($state.State -eq 'Off') { Start-VM -VM $state | Out-Null }
    } while ((Get-Date) -lt $Deadline)
    throw "PowerShell Direct indisponible avant le délai de $TimeoutMinutes minutes."
}

function Send-SetupBootKey {
    param([Parameter(Mandatory)][guid]$VMId)
    $deadline = (Get-Date).AddSeconds(8)
    do {
        $keyboard = Get-CimInstance -Namespace root\virtualization\v2 -ClassName Msvm_Keyboard -ErrorAction SilentlyContinue |
            Where-Object SystemName -eq $VMId.ToString()
        if ($keyboard) {
            Invoke-CimMethod -InputObject $keyboard -MethodName TypeKey -Arguments @{ KeyCode = 32 } | Out-Null
        }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)
}

function Remove-TransientMedia {
    Get-VMDvdDrive -VMName $vmName -ErrorAction SilentlyContinue | Set-VMDvdDrive -Path $null -ErrorAction SilentlyContinue
    foreach ($path in @($answerFile, $seedIso)) {
        if (Test-Path -LiteralPath $path) {
            & icacls.exe $path /grant:r "${env:USERNAME}:F" | Out-Null
            Remove-Item -LiteralPath $path -Force
        }
    }
}

Assert-ChildPath -Parent $root -Child $vmDirectory
Assert-ChildPath -Parent $root -Child $seedDirectory
if (-not (Test-Path -LiteralPath $sourceIso -PathType Leaf)) { throw "ISO Windows absente : $sourceIso" }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $sourceIso).Hash -ne $expectedIsoHash) { throw 'Empreinte de l ISO Windows invalide.' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Runtime Python Marvin absent : $python" }
Import-Module Hyper-V -ErrorAction Stop
$null = Get-VMSwitch -Name $SwitchName -ErrorAction Stop

if (-not $PSCmdlet.ShouldProcess($vmName, 'Recréer et installer Windows 11 Pro sans assistance')) {
    Write-Result @{ status = 'declined'; vm_name = $vmName }
    return
}

try {
    $existing = Get-VM -Name $vmName -ErrorAction SilentlyContinue
    if ($existing) {
        if ($existing.State -ne 'Off') { Stop-VM -VM $existing -TurnOff -Force }
        Remove-VM -VM $existing -Force
    }
    if (Test-Path -LiteralPath $vmDirectory) { Remove-Item -LiteralPath $vmDirectory -Recurse -Force }

    New-Item -ItemType Directory -Path $seedDirectory -Force | Out-Null
    & icacls.exe $seedDirectory /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /T /C | Out-Null
    & $python (Join-Path $PSScriptRoot 'prepare-vm-unattended.py') windows11 --output $seedDirectory --windows-image-index 6 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'La génération Autounattend a échoué.' }
    & (Join-Path $PSScriptRoot 'build-windows-unattend-iso.ps1') -AnswerFile $answerFile -OutputIso $seedIso
    if ($LASTEXITCODE -ne 0) { throw 'La génération du média Autounattend a échoué.' }

    & $python (Join-Path $PSScriptRoot 'materialize-vm-secret.py') --key vm_lab.windows11.guest_password --output $secretPath | Out-Null
    & icacls.exe $secretPath /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
    $password = Get-Content -LiteralPath $secretPath -Raw
    $credential = [PSCredential]::new('marvin', (ConvertTo-SecureString $password -AsPlainText -Force))
    $password = $null

    New-Item -ItemType Directory -Path $vmDirectory -Force | Out-Null
    $vhd = Join-Path $vmDirectory ($vmName + '.vhdx')
    $vm = New-VM -Name $vmName -Generation 2 -Path $vmDirectory -MemoryStartupBytes 4GB `
        -NewVHDPath $vhd -NewVHDSizeBytes 80GB -SwitchName $SwitchName
    $created = $true
    Set-VM -VM $vm -ProcessorCount 4 -DynamicMemory -MemoryMinimumBytes 3GB `
        -MemoryMaximumBytes 6GB -AutomaticCheckpointsEnabled $false -CheckpointType ProductionOnly
    Set-VMKeyProtector -VMName $vmName -NewLocalKeyProtector
    Enable-VMTPM -VMName $vmName
    $setupDvd = Add-VMDvdDrive -VMName $vmName -Path $sourceIso -Passthru
    $null = Add-VMDvdDrive -VMName $vmName -Path $seedIso
    Set-VMFirmware -VMName $vmName -EnableSecureBoot Off -SecureBootTemplate MicrosoftWindows -FirstBootDevice $setupDvd
    Start-VM -VM $vm | Out-Null
    Send-SetupBootKey -VMId $vm.VMId

    $session = New-GuestSession -Credential $credential -Deadline (Get-Date).AddMinutes($TimeoutMinutes)
    $setupEvidence = Invoke-Command -Session $session -ScriptBlock {
        [ordered]@{
            powershell_direct = $true
            initial_admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
            os = (Get-CimInstance Win32_OperatingSystem).Caption
            build = [Environment]::OSVersion.Version.ToString()
        }
    }
    if (-not $setupEvidence.initial_admin) { throw 'Le compte initial Windows n est pas administrateur pour le provisionnement.' }
    Remove-PSSession $session
    $session = $null

    & (Join-Path $PSScriptRoot 'provision-windows-vm-lab.ps1') -TimeoutMinutes 75
    if ($LASTEXITCODE -ne 0) { throw 'Le provisionnement Windows Test Forge a échoué.' }
    $provision = Get-Content -LiteralPath $provisionResultPath -Raw | ConvertFrom-Json
    if ($provision.status -ne 'completed') { throw "Provisionnement Windows incomplet : $($provision.status)" }

    Remove-TransientMedia
    Write-Result @{
        status = 'completed'; vm_name = $vmName; checkpoint = $provision.checkpoint
        setup = $setupEvidence; provisioning = $provision
        transient_answer_destroyed = (-not (Test-Path -LiteralPath $answerFile))
        transient_seed_iso_destroyed = (-not (Test-Path -LiteralPath $seedIso))
        host_network_modified = $false; guest_network_connected_during_install = $true
    }
    Get-Content -LiteralPath $resultPath -Raw
}
catch {
    if ($session) { Remove-PSSession $session -ErrorAction SilentlyContinue; $session = $null }
    if ($created) {
        $failed = Get-VM -Name $vmName -ErrorAction SilentlyContinue
        if ($failed -and $failed.State -ne 'Off') { Stop-VM -VM $failed -TurnOff -Force -ErrorAction SilentlyContinue }
    }
    Remove-TransientMedia
    Write-Result @{
        status = 'failed'; vm_name = $vmName; error = $_.Exception.Message
        error_id = $_.FullyQualifiedErrorId; error_position = $_.InvocationInfo.PositionMessage
        script_stack = $_.ScriptStackTrace; host_network_modified = $false
    }
    throw
}
finally {
    if ($session) { Remove-PSSession $session -ErrorAction SilentlyContinue }
    $password = $null
    if (Test-Path -LiteralPath $secretPath) { Remove-Item -LiteralPath $secretPath -Force }
}
