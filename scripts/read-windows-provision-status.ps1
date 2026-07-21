[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$secretPath = Join-Path $root 'data\.windows-provision-status-secret.txt'
$session = $null
$password = $null
try {
    & (Join-Path $root 'backend\.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'materialize-vm-secret.py') --key vm_lab.windows11.guest_password --output $secretPath | Out-Null
    & icacls.exe $secretPath /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
    $password = Get-Content -LiteralPath $secretPath -Raw
    $credential = [PSCredential]::new('marvin', (ConvertTo-SecureString $password -AsPlainText -Force))
    $password = $null
    $session = New-PSSession -VMName 'Marvin-Windows11-TestForge' -Credential $credential
    Invoke-Command -Session $session -ScriptBlock {
        $result = 'C:\ProgramData\MarvinProvision\result.json'
        $progress = 'C:\ProgramData\MarvinProvision\progress.json'
        [ordered]@{
            result = if (Test-Path -LiteralPath $result) { Get-Content -LiteralPath $result -Raw | ConvertFrom-Json } else { $null }
            progress = if (Test-Path -LiteralPath $progress) { Get-Content -LiteralPath $progress -Raw | ConvertFrom-Json } else { $null }
            console_user = [string](quser.exe 2>&1 | Out-String)
            is_admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
            autologon = [ordered]@{
                enabled = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon').AutoAdminLogon
                password_present = [bool](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon').DefaultPassword
            }
        } | ConvertTo-Json -Depth 8
    }
}
finally {
    if ($session) { Remove-PSSession $session -ErrorAction SilentlyContinue }
    $password = $null
    if (Test-Path -LiteralPath $secretPath) { Remove-Item -LiteralPath $secretPath -Force }
}
