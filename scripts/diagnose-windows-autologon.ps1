[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$secretPath = Join-Path $projectRoot 'data\.windows-autologon-diagnostic-secret.txt'
$session = $null
$password = $null

try {
    & $python (Join-Path $PSScriptRoot 'materialize-vm-secret.py') --key vm_lab.windows11.guest_password --output $secretPath | Out-Null
    & icacls.exe $secretPath /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
    $password = Get-Content -LiteralPath $secretPath -Raw
    $credential = [PSCredential]::new('marvin', (ConvertTo-SecureString $password -AsPlainText -Force))
    $password = $null
    $session = New-PSSession -VMName 'Marvin-Windows11-TestForge' -Credential $credential
    Invoke-Command -Session $session -ScriptBlock {
        $path = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
        $properties = Get-ItemProperty -Path $path
        [ordered]@{
            computer = $env:COMPUTERNAME
            auto_admin_logon = $properties.AutoAdminLogon
            default_user = $properties.DefaultUserName
            default_domain = $properties.DefaultDomainName
            force_auto_logon = $properties.ForceAutoLogon
            default_password_present = [bool]$properties.DefaultPassword
            sessions = [string](quser.exe 2>&1 | Out-String)
            explorer_count = @(Get-Process -Name explorer -ErrorAction SilentlyContinue).Count
            setup = [ordered]@{
                system_setup_in_progress = (Get-ItemProperty 'HKLM:\SYSTEM\Setup').SystemSetupInProgress
                oobe_in_progress = (Get-ItemProperty 'HKLM:\SYSTEM\Setup').OOBEInProgress
                setup_type = (Get-ItemProperty 'HKLM:\SYSTEM\Setup').SetupType
                setup_phase = (Get-ItemProperty 'HKLM:\SYSTEM\Setup\Status\ChildCompletion' -ErrorAction SilentlyContinue).setup
            }
            logon_failures = @(Get-WinEvent -FilterHashtable @{ LogName = 'Security'; Id = 4625; StartTime = (Get-Date).AddMinutes(-30) } -MaxEvents 10 -ErrorAction SilentlyContinue |
                Select-Object TimeCreated, Id, Message)
            provision_result = if (Test-Path -LiteralPath 'C:\ProgramData\MarvinProvision\result.json') {
                Get-Content -LiteralPath 'C:\ProgramData\MarvinProvision\result.json' -Raw | ConvertFrom-Json
            } else { $null }
            provision_task = Get-ScheduledTask -TaskName 'Marvin-Provision-Toolchains' -ErrorAction SilentlyContinue |
                Select-Object TaskName, State
            provision_task_info = [string](schtasks.exe /query /tn 'Marvin-Provision-Toolchains' /v /fo list 2>&1 | Out-String)
            provision_script = if (Test-Path -LiteralPath 'C:\ProgramData\MarvinProvision\install-toolchains.ps1') {
                @(Get-Content -LiteralPath 'C:\ProgramData\MarvinProvision\install-toolchains.ps1')
            } else { @() }
        } | ConvertTo-Json -Depth 6
    }
}
finally {
    if ($session) { Remove-PSSession $session -ErrorAction SilentlyContinue }
    $password = $null
    if (Test-Path -LiteralPath $secretPath) { Remove-Item -LiteralPath $secretPath -Force }
}
