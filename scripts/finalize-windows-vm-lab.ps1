[CmdletBinding()]
param(
    [ValidateRange(5, 30)]
    [int]$TimeoutMinutes = 12
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$vmName = 'Marvin-Windows11-TestForge'
$checkpointName = 'Marvin-Clean'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$secretPath = Join-Path $projectRoot 'data\.windows-vm-finalize-secret.txt'
$resultPath = Join-Path $projectRoot 'data\windows-vm-install-result.json'
$session = $null
$password = $null

function New-GuestSession {
    param([Parameter(Mandatory)][PSCredential]$Credential, [Parameter(Mandatory)][datetime]$Deadline)
    do {
        try { return New-PSSession -VMName $vmName -Credential $Credential -ErrorAction Stop }
        catch { Start-Sleep -Seconds 5 }
    } while ((Get-Date) -lt $Deadline)
    throw 'PowerShell Direct indisponible avant expiration du délai.'
}

function Wait-VMOff {
    param([Parameter(Mandatory)][datetime]$Deadline)
    do {
        Start-Sleep -Seconds 3
        $state = (Get-VM -Name $vmName -ErrorAction Stop).State
    } while ($state -ne 'Off' -and (Get-Date) -lt $Deadline)
    if ($state -ne 'Off') { throw 'La VM Windows ne s est pas arrêtée proprement.' }
}

function Write-Result {
    param([Parameter(Mandatory)][hashtable]$Value)
    $Value.timestamp = (Get-Date).ToString('o')
    $temporary = $resultPath + '.tmp'
    $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $resultPath -Force
}

try {
    Import-Module Hyper-V -ErrorAction Stop
    $vm = Get-VM -Name $vmName -ErrorAction Stop
    if ($vm.State -eq 'Off') { Start-VM -VM $vm | Out-Null }

    & $python (Join-Path $PSScriptRoot 'materialize-vm-secret.py') --key vm_lab.windows11.guest_password --output $secretPath | Out-Null
    & icacls.exe $secretPath /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
    $password = Get-Content -LiteralPath $secretPath -Raw
    $credential = [PSCredential]::new('marvin', (ConvertTo-SecureString $password -AsPlainText -Force))
    $password = $null

    $session = New-GuestSession -Credential $credential -Deadline (Get-Date).AddMinutes($TimeoutMinutes)
    $validation = Invoke-Command -Session $session -ScriptBlock {
        $winlogon = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
        $packageResultPath = 'C:\ProgramData\MarvinProvision\result.json'
        [ordered]@{
            username = [Environment]::UserName
            is_admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
            autologon_enabled = [string]$winlogon.AutoAdminLogon
            autologon_password_present = [bool]$winlogon.DefaultPassword
            os = (Get-CimInstance Win32_OperatingSystem).Caption
            build = [Environment]::OSVersion.Version.ToString()
            python = [string](& 'C:\Users\marvin\AppData\Local\Programs\Python\Python313\python.exe' --version 2>&1)
            node = [string](& 'C:\Program Files\nodejs\node.exe' --version 2>&1)
            git = [string](& 'C:\Program Files\Git\cmd\git.exe' --version 2>&1)
            go = [string](& 'C:\Program Files\Go\bin\go.exe' version 2>&1)
            dotnet = [string](& 'C:\Program Files\dotnet\dotnet.exe' --version 2>&1)
            packages = if (Test-Path -LiteralPath $packageResultPath) {
                (Get-Content -LiteralPath $packageResultPath -Raw | ConvertFrom-Json).packages
            } else { @() }
        }
    }
    if ($validation.username -ne 'marvin' -or $validation.is_admin) { throw 'Le compte invité final n est pas un utilisateur Marvin standard.' }
    if ($validation.autologon_enabled -ne '0' -or $validation.autologon_password_present) { throw 'AutoLogon ou son mot de passe temporaire subsiste.' }
    foreach ($property in @('python', 'node', 'git', 'go', 'dotnet')) {
        if (-not [string]$validation.$property) { throw "La chaîne d outils $property n a retourné aucune version." }
    }

    Invoke-Command -Session $session -ScriptBlock { & shutdown.exe /s /t 0 /f /d p:4:1 /c 'Marvin VM Lab Secure Boot validation' }
    Remove-PSSession $session
    $session = $null
    Wait-VMOff -Deadline (Get-Date).AddMinutes(5)

    Get-VMDvdDrive -VMName $vmName | Set-VMDvdDrive -Path $null
    $disk = Get-VMHardDiskDrive -VMName $vmName | Select-Object -First 1
    Set-VMFirmware -VMName $vmName -FirstBootDevice $disk -EnableSecureBoot On
    Start-VM -Name $vmName | Out-Null
    $session = New-GuestSession -Credential $credential -Deadline (Get-Date).AddMinutes($TimeoutMinutes)
    $guestBoot = Invoke-Command -Session $session -ScriptBlock { [ordered]@{ booted = $true; build = [Environment]::OSVersion.Version.ToString() } }
    $firmware = Get-VMFirmware -VMName $vmName
    $secureBoot = [ordered]@{ booted = [bool]$guestBoot.booted; enabled = ($firmware.SecureBoot -eq 'On'); template = [string]$firmware.SecureBootTemplate }
    if (-not $secureBoot.enabled) { throw 'Windows a démarré mais Secure Boot n est pas actif.' }
    Invoke-Command -Session $session -ScriptBlock { & shutdown.exe /s /t 0 /f /d p:4:1 /c 'Marvin VM Lab clean checkpoint' }
    Remove-PSSession $session
    $session = $null
    Wait-VMOff -Deadline (Get-Date).AddMinutes(5)

    Get-VMCheckpoint -VMName $vmName -Name $checkpointName -ErrorAction SilentlyContinue | Remove-VMCheckpoint -Confirm:$false
    Checkpoint-VM -Name $vmName -SnapshotName $checkpointName | Out-Null
    & $python (Join-Path $PSScriptRoot 'configure-hyperv-runner-from-vm.py') | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'La liaison du runner Hyper-V Test Forge a échoué.' }

    $seedRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Marvin\library\vm\seeds\windows11'
    foreach ($leaf in @('Autounattend.xml', 'windows11-marvin-autounattend.iso')) {
        $candidate = [IO.Path]::GetFullPath((Join-Path $seedRoot $leaf))
        if ($candidate.StartsWith(([IO.Path]::GetFullPath($seedRoot) + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $candidate)) {
            & icacls.exe $candidate /grant:r "${env:USERNAME}:F" | Out-Null
            Remove-Item -LiteralPath $candidate -Force
        }
    }

    Write-Result @{
        status = 'completed'; vm_name = $vmName; checkpoint = $checkpointName
        evidence = $validation; secure_boot = $secureBoot
        final_user_is_admin = $false; host_network_modified = $false
    }
    Get-Content -LiteralPath $resultPath -Raw
}
catch {
    Write-Result @{
        status = 'failed'; vm_name = $vmName; error = $_.Exception.Message
        error_position = $_.InvocationInfo.PositionMessage; script_stack = $_.ScriptStackTrace
        host_network_modified = $false
    }
    throw
}
finally {
    if ($session) { Remove-PSSession $session -ErrorAction SilentlyContinue }
    $password = $null
    if (Test-Path -LiteralPath $secretPath) { Remove-Item -LiteralPath $secretPath -Force }
}
