[CmdletBinding()]
param(
    [ValidateRange(15, 120)]
    [int]$TimeoutMinutes = 75
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$vmName = 'Marvin-Windows11-TestForge'
$checkpointName = 'Marvin-Clean'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$secretPath = Join-Path $projectRoot 'data\.windows-vm-provision-secret.txt'
$adminSecretPath = Join-Path $projectRoot 'data\.windows-vm-provision-admin-secret.txt'
$resultPath = Join-Path $projectRoot 'data\windows-vm-provision-result.json'
$session = $null
$password = $null

function New-GuestSession {
    param([Parameter(Mandatory)][PSCredential]$Credential, [Parameter(Mandatory)][datetime]$Deadline)
    do {
        try { return New-PSSession -VMName $vmName -Credential $Credential -ErrorAction Stop } catch { Start-Sleep -Seconds 5 }
    } while ((Get-Date) -lt $Deadline)
    throw 'PowerShell Direct indisponible.'
}

function Write-Result {
    param([Parameter(Mandatory)][hashtable]$Value)
    $Value.timestamp = (Get-Date).ToString('o')
    $temporary = $resultPath + '.tmp'
    $Value | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $resultPath -Force
}

try {
    $vm = Get-VM -Name $vmName -ErrorAction Stop
    Get-VMDvdDrive -VMName $vmName | Where-Object { $_.Path -and -not (Test-Path -LiteralPath $_.Path) } | Set-VMDvdDrive -Path $null
    $disk = Get-VMHardDiskDrive -VMName $vmName | Select-Object -First 1
    Set-VMFirmware -VMName $vmName -FirstBootDevice $disk -EnableSecureBoot Off
    if ($vm.State -eq 'Off') { Start-VM -VM $vm | Out-Null }

    & $python (Join-Path $PSScriptRoot 'materialize-vm-secret.py') --key vm_lab.windows11.guest_password --output $secretPath | Out-Null
    & $python (Join-Path $PSScriptRoot 'materialize-vm-secret.py') --key vm_lab.windows11.admin_password --output $adminSecretPath | Out-Null
    & icacls.exe $secretPath /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
    & icacls.exe $adminSecretPath /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
    $password = Get-Content -LiteralPath $adminSecretPath -Raw
    $credential = [PSCredential]::new('marvin-lab-admin', (ConvertTo-SecureString $password -AsPlainText -Force))
    $userPassword = Get-Content -LiteralPath $secretPath -Raw
    $userCredential = [PSCredential]::new('marvin', (ConvertTo-SecureString $userPassword -AsPlainText -Force))
    $userPassword = $null
    $session = New-GuestSession -Credential $credential -Deadline (Get-Date).AddMinutes(5)
    Invoke-Command -Session $session -ArgumentList $password -ScriptBlock {
        param([string]$TemporaryPassword)
        Unregister-ScheduledTask -TaskName 'Marvin-Provision-Toolchains' -Confirm:$false -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath 'C:\ProgramData\MarvinProvision\result.json' -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath 'C:\ProgramData\MarvinProvision\progress.json' -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath 'C:\ProgramData\MarvinProvision\install-toolchains.ps1' -Force -ErrorAction SilentlyContinue
        $winlogon = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
        Set-ItemProperty -Path $winlogon -Name AutoAdminLogon -Value '1' -Type String
        Set-ItemProperty -Path $winlogon -Name DefaultUserName -Value 'marvin-lab-admin' -Type String
        Set-ItemProperty -Path $winlogon -Name DefaultDomainName -Value ([Environment]::MachineName) -Type String
        Set-ItemProperty -Path $winlogon -Name DefaultPassword -Value $TemporaryPassword -Type String
        Set-ItemProperty -Path $winlogon -Name ForceAutoLogon -Value '1' -Type String
        Set-ItemProperty -Path $winlogon -Name AutoLogonCount -Value 10 -Type DWord
        & shutdown.exe /r /t 0 /f /d p:4:1 /c 'Marvin VM Lab provisioning'
    }
    $password = $null
    Remove-PSSession $session
    $session = $null
    Start-Sleep -Seconds 30
    $session = New-GuestSession -Credential $credential -Deadline (Get-Date).AddMinutes(10)

    $interactiveReady = Invoke-Command -Session $session -ScriptBlock {
        $deadline = (Get-Date).AddMinutes(5)
        do {
            $explorer = Get-CimInstance Win32_Process -Filter "Name='explorer.exe'" | Select-Object -First 1
            if (-not $explorer) { Start-Sleep -Seconds 5 }
        } while (-not $explorer -and (Get-Date) -lt $deadline)
        [bool]$explorer
    }
    if (-not $interactiveReady) { throw 'La session locale Marvin ne s est pas ouverte.' }

    $taskInfo = Invoke-Command -Session $session -ScriptBlock {
        $root = 'C:\ProgramData\MarvinProvision'
        $scriptPath = Join-Path $root 'install-toolchains.ps1'
        $resultPath = Join-Path $root 'result.json'
        $taskName = 'Marvin-Provision-Toolchains'
        New-Item -ItemType Directory -Path $root -Force | Out-Null
        Remove-Item -LiteralPath $resultPath -Force -ErrorAction SilentlyContinue
        $content = @'
$ErrorActionPreference = 'Stop'
$packages = @('Python.Python.3.13','OpenJS.NodeJS.LTS','Git.Git','GoLang.Go','Microsoft.DotNet.SDK.10')
$rows = @()
try {
  $appInstaller = Get-AppxPackage -Name Microsoft.DesktopAppInstaller | Sort-Object Version -Descending | Select-Object -First 1
  if (-not $appInstaller) { throw 'Microsoft Desktop App Installer est absent.' }
  $winget = Join-Path $appInstaller.InstallLocation 'winget.exe'
  if (-not (Test-Path -LiteralPath $winget)) { throw "WinGet introuvable dans $($appInstaller.InstallLocation)." }
  foreach ($package in $packages) {
    [ordered]@{ success=$false; in_progress=$package; packages=$rows } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath 'C:\ProgramData\MarvinProvision\progress.json' -Encoding UTF8
    $code = 1
    $accepted = $false
    $attempt = 0
    while (-not $accepted -and $attempt -lt 3) {
      $attempt++
      & $winget install --id $package --exact --scope machine --silent --disable-interactivity --accept-source-agreements --accept-package-agreements
      $code = $LASTEXITCODE
      $accepted = $code -in @(0, -1978335189, -1978335212, 3010)
      if (-not $accepted -and $attempt -lt 3) {
        & $winget source update --disable-interactivity | Out-Null
        Start-Sleep -Seconds (5 * $attempt)
      }
    }
    $rows += [ordered]@{ id=$package; exit_code=$code; accepted=$accepted; attempts=$attempt }
    [ordered]@{ success=$false; completed=$package; packages=$rows } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath 'C:\ProgramData\MarvinProvision\progress.json' -Encoding UTF8
    if (-not $accepted) { throw "WinGet failed for $package with $code" }
  }
  [ordered]@{ success=$true; packages=$rows } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath 'C:\ProgramData\MarvinProvision\result.json' -Encoding UTF8
} catch {
  [ordered]@{ success=$false; error=$_.Exception.Message; packages=$rows } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath 'C:\ProgramData\MarvinProvision\result.json' -Encoding UTF8
  exit 1
}
'@
        Set-Content -LiteralPath $scriptPath -Value $content -Encoding UTF8
        $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
        $principal = New-ScheduledTaskPrincipal -UserId 'marvin' -LogonType Interactive -RunLevel Highest
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User 'marvin'
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Trigger $trigger -Settings $settings -Force | Out-Null
        Start-ScheduledTask -TaskName $taskName
        [ordered]@{ task_name=$taskName; result_path=$resultPath; root=$root }
    }

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $packageResult = $null
    do {
        Start-Sleep -Seconds 10
        try {
            if (-not $session -or $session.State -ne 'Opened') {
                if ($session) { Remove-PSSession $session -ErrorAction SilentlyContinue }
                $session = New-GuestSession -Credential $credential -Deadline (Get-Date).AddMinutes(3)
            }
            $packageResult = Invoke-Command -Session $session -ArgumentList $taskInfo.result_path -ScriptBlock {
                param($Path)
                if (Test-Path -LiteralPath $Path) { Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json } else { $null }
            }
        } catch {
            if ($session) { Remove-PSSession $session -ErrorAction SilentlyContinue }
            $session = $null
        }
    } while (-not $packageResult -and (Get-Date) -lt $deadline)
    if (-not $packageResult) { throw 'Le provisionnement WinGet a dépassé le délai.' }
    if (-not $packageResult.success) { throw "Le provisionnement WinGet a échoué : $($packageResult.error)" }

    $finalize = Invoke-Command -Session $session -ArgumentList $taskInfo.task_name,$taskInfo.root,@($packageResult.packages) -ScriptBlock {
        param($TaskName,$Root,$Packages)
        $winlogon = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
        Remove-ItemProperty -Path $winlogon -Name DefaultPassword -ErrorAction SilentlyContinue
        Set-ItemProperty -Path $winlogon -Name AutoAdminLogon -Value '0' -Type String
        Set-ItemProperty -Path $winlogon -Name ForceAutoLogon -Value '0' -Type String
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        $sensitiveFiles = @('C:\Windows\Panther\Unattend.xml','C:\Windows\Panther\Unattend\Unattend.xml','C:\Windows\System32\Sysprep\unattend.xml')
        foreach ($file in $sensitiveFiles) { Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue }
        $remoteGroup = Get-LocalGroup -SID 'S-1-5-32-580'
        Add-LocalGroupMember -Group $remoteGroup -Member 'marvin' -ErrorAction SilentlyContinue
        & shutdown.exe /r /t 0 /f /d p:4:1 /c 'Marvin VM Lab least privilege finalization'
        [ordered]@{ packages=$Packages; build=[Environment]::OSVersion.Version.ToString() }
    }
    Remove-PSSession $session
    $session = $null
    Start-Sleep -Seconds 25
    $session = New-GuestSession -Credential $userCredential -Deadline (Get-Date).AddMinutes(10)
    $evidence = Invoke-Command -Session $session -ScriptBlock {
        $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        [ordered]@{
            username=[Environment]::UserName; is_admin=$isAdmin
            os=(Get-CimInstance Win32_OperatingSystem).Caption; build=[Environment]::OSVersion.Version.ToString()
            python=[string](& (Get-Command python.exe -ErrorAction Stop).Source --version 2>&1)
            node=[string](& 'C:\Program Files\nodejs\node.exe' --version 2>&1)
            git=[string](& 'C:\Program Files\Git\cmd\git.exe' --version 2>&1)
            go=[string](& 'C:\Program Files\Go\bin\go.exe' version 2>&1)
            dotnet=[string](& 'C:\Program Files\dotnet\dotnet.exe' --version 2>&1)
        }
    }
    if ($evidence.is_admin -or $evidence.username -ne 'marvin') { throw 'Le compte final n est pas un utilisateur Marvin standard.' }
    Invoke-Command -Session $session -ScriptBlock { & shutdown.exe /s /t 0 /f /d p:4:1 /c 'Marvin VM Lab validation' }
    Remove-PSSession $session
    $session = $null
    $deadline = (Get-Date).AddMinutes(5)
    do { Start-Sleep -Seconds 5; $vm = Get-VM -Name $vmName } while ($vm.State -ne 'Off' -and (Get-Date) -lt $deadline)
    if ($vm.State -ne 'Off') { throw 'Windows ne s est pas arrêté proprement.' }
    Get-VMDvdDrive -VMName $vmName | Set-VMDvdDrive -Path $null
    Set-VMFirmware -VMName $vmName -FirstBootDevice (Get-VMHardDiskDrive -VMName $vmName | Select-Object -First 1) -EnableSecureBoot On
    Start-VM -Name $vmName | Out-Null
    $session = New-GuestSession -Credential $userCredential -Deadline (Get-Date).AddMinutes(10)
    $guestBoot = Invoke-Command -Session $session -ScriptBlock { [ordered]@{ booted=$true; build=[Environment]::OSVersion.Version.ToString() } }
    $firmware = Get-VMFirmware -VMName $vmName
    $secureBoot = [ordered]@{ booted=[bool]$guestBoot.booted; enabled=($firmware.SecureBoot -eq 'On'); template=[string]$firmware.SecureBootTemplate }
    Invoke-Command -Session $session -ScriptBlock { & shutdown.exe /s /t 0 /f /d p:4:1 /c 'Marvin VM Lab clean checkpoint' }
    Remove-PSSession $session
    $session = $null
    $deadline = (Get-Date).AddMinutes(5)
    do { Start-Sleep -Seconds 5; $vm = Get-VM -Name $vmName } while ($vm.State -ne 'Off' -and (Get-Date) -lt $deadline)
    if ($vm.State -ne 'Off') { throw 'Arrêt final Windows impossible.' }
    Get-VMCheckpoint -VMName $vmName -Name $checkpointName -ErrorAction SilentlyContinue | Remove-VMCheckpoint -Confirm:$false
    Checkpoint-VM -Name $vmName -SnapshotName $checkpointName | Out-Null
    & $python (Join-Path $PSScriptRoot 'configure-hyperv-runner-from-vm.py') | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Liaison Hyper-V Test Forge impossible.' }
    Write-Result @{ status='completed'; vm_name=$vmName; checkpoint=$checkpointName; evidence=$evidence; secure_boot=$secureBoot; packages=$packageResult.packages; final_user_is_admin=$false; host_network_modified=$false }
    Get-Content -LiteralPath $resultPath -Raw
}
catch {
    Write-Result @{ status='failed'; vm_name=$vmName; error=$_.Exception.Message; error_position=$_.InvocationInfo.PositionMessage; script_stack=$_.ScriptStackTrace; host_network_modified=$false }
    throw
}
finally {
    if ($session) { Remove-PSSession $session -ErrorAction SilentlyContinue }
    $password = $null
    if (Test-Path -LiteralPath $secretPath) { Remove-Item -LiteralPath $secretPath -Force }
    if (Test-Path -LiteralPath $adminSecretPath) { Remove-Item -LiteralPath $adminSecretPath -Force }
}
