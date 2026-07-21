[CmdletBinding()]
param([ValidateRange(1, 15)][int]$TimeoutMinutes = 5)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$vmName = 'Marvin-Windows11-TestForge'
$secretKey = 'vm_lab.windows11.guest_password'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$secretPath = Join-Path $projectRoot 'data\.windows-vm-diagnostic-secret.txt'
$session = $null
$password = $null
try {
    $vm = Get-VM -Name $vmName -ErrorAction Stop
    Get-VMDvdDrive -VMName $vmName | Where-Object { $_.Path -and -not (Test-Path -LiteralPath $_.Path) } |
        Set-VMDvdDrive -Path $null
    $disk = Get-VMHardDiskDrive -VMName $vmName | Select-Object -First 1
    Set-VMFirmware -VMName $vmName -FirstBootDevice $disk -EnableSecureBoot Off
    if ($vm.State -eq 'Off') { Start-VM -VM $vm | Out-Null }
    & $python (Join-Path $PSScriptRoot 'materialize-vm-secret.py') --key $secretKey --output $secretPath | Out-Null
    & icacls.exe $secretPath /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
    $password = Get-Content -LiteralPath $secretPath -Raw
    $credential = [PSCredential]::new('marvin', (ConvertTo-SecureString $password -AsPlainText -Force))
    $password = $null
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    do {
        try { $session = New-PSSession -VMName $vmName -Credential $credential -ErrorAction Stop } catch { Start-Sleep -Seconds 5 }
    } while (-not $session -and (Get-Date) -lt $deadline)
    if (-not $session) { throw 'PowerShell Direct indisponible.' }
    Invoke-Command -Session $session -ScriptBlock {
        $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        $app = Get-AppxPackage -AllUsers Microsoft.DesktopAppInstaller | Sort-Object Version -Descending | Select-Object -First 1
        $winget = if ($app) { Join-Path $app.InstallLocation 'winget.exe' } else { $null }
        $wingetDirect = $null
        $wingetStartProcess = $null
        if ($winget) {
            try { $wingetDirect = [string](& $winget --version 2>&1) } catch { $wingetDirect = 'ERROR: ' + $_.Exception.Message }
            try {
                $probe = Start-Process -FilePath $winget -ArgumentList @('--version') -Wait -PassThru -WindowStyle Hidden
                $wingetStartProcess = 'exit=' + $probe.ExitCode
            } catch { $wingetStartProcess = 'ERROR: ' + $_.Exception.Message }
        }
        $scheduledWinget = $null
        $probeRoot = 'C:\ProgramData\MarvinProvisionProbe'
        $probeScript = Join-Path $probeRoot 'probe.ps1'
        $probeResult = Join-Path $probeRoot 'result.txt'
        $probeTask = 'Marvin-WinGet-Probe'
        try {
            New-Item -ItemType Directory -Path $probeRoot -Force | Out-Null
            Set-Content -LiteralPath $probeScript -Encoding UTF8 -Value "& winget.exe --version 2>&1 | Set-Content -LiteralPath '$probeResult' -Encoding UTF8"
            $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$probeScript`""
            $principal = New-ScheduledTaskPrincipal -UserId 'marvin' -LogonType Interactive -RunLevel Highest
            Register-ScheduledTask -TaskName $probeTask -Action $action -Principal $principal -Force | Out-Null
            Start-ScheduledTask -TaskName $probeTask
            $probeDeadline = (Get-Date).AddSeconds(60)
            do { Start-Sleep -Seconds 2; $probeState = Get-ScheduledTask -TaskName $probeTask } while ($probeState.State -eq 'Running' -and (Get-Date) -lt $probeDeadline)
            $scheduledWinget = if (Test-Path $probeResult) { Get-Content -LiteralPath $probeResult -Raw } else { 'ERROR: no result, state=' + $probeState.State }
        } catch { $scheduledWinget = 'ERROR: ' + $_.Exception.Message }
        finally { Unregister-ScheduledTask -TaskName $probeTask -Confirm:$false -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue }
        [ordered]@{
            user = [Environment]::UserName; admin = $admin
            os = (Get-CimInstance Win32_OperatingSystem).Caption
            build = [Environment]::OSVersion.Version.ToString()
            app_installer_version = [string]$app.Version
            winget_path = $winget
            winget_exists = $(if ($winget) { Test-Path $winget } else { $false })
            winget_direct = $wingetDirect; winget_start_process = $wingetStartProcess
            winget_scheduled_interactive = $scheduledWinget
            winget_acl = $(if ($winget) { & icacls.exe $winget 2>&1 } else { @() })
            groups = @(whoami.exe /groups)
        }
    } | ConvertTo-Json -Depth 6
}
finally {
    if ($session) { Remove-PSSession $session -ErrorAction SilentlyContinue }
    $password = $null
    if (Test-Path -LiteralPath $secretPath) { Remove-Item -LiteralPath $secretPath -Force }
}
