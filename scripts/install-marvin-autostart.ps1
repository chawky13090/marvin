[CmdletBinding(SupportsShouldProcess = $true)]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$StartBatch = Join-Path $Root 'start.bat'
$TaskName = 'Marvin - Demarrage automatique'
$InteractiveUser = [string](Get-CimInstance Win32_ComputerSystem).UserName

if (-not (Test-Path -LiteralPath $StartBatch -PathType Leaf)) {
    throw "Lanceur Marvin introuvable : $StartBatch"
}
if ([string]::IsNullOrWhiteSpace($InteractiveUser)) {
    throw 'Aucune session utilisateur interactive détectée. Connectez-vous puis relancez ce script.'
}

$Action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" `
    -Argument "/d /c call `"$StartBatch`"" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $InteractiveUser
$Principal = New-ScheduledTaskPrincipal -UserId $InteractiveUser `
    -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

if ($PSCmdlet.ShouldProcess($TaskName, "Enregistrer le démarrage à l'ouverture de session de $InteractiveUser")) {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
        -Principal $Principal -Settings $Settings -Force | Out-Null
}

foreach ($Name in @('Marvin - Frontend', 'Marvin - Backend', 'Marvin - HTTPS')) {
    if ($PSCmdlet.ShouldProcess("Règle pare-feu $Name", 'Supprimer la règle historique')) {
        Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    }
}

$HttpsState = Join-Path $Root 'runtime\https\state.json'
$HttpsEnabled = $false
if (Test-Path -LiteralPath $HttpsState) {
    try { $HttpsEnabled = (Get-Content -LiteralPath $HttpsState -Raw | ConvertFrom-Json).enabled -eq $true } catch {}
}
if ($HttpsEnabled -and $PSCmdlet.ShouldProcess('Pare-feu Windows', 'Autoriser Marvin HTTPS depuis le sous-réseau local')) {
    New-NetFirewallRule -DisplayName 'Marvin - HTTPS' -Direction Inbound `
        -LocalPort 8443 -Protocol TCP -Action Allow -Profile Domain,Private `
        -RemoteAddress LocalSubnet | Out-Null
}

[pscustomobject]@{
    success = $true
    task = $TaskName
    user = $InteractiveUser
    logon_type = 'Interactive'
    run_level = 'Limited'
    https_firewall = $HttpsEnabled
    raw_frontend_backend_exposed = $false
} | ConvertTo-Json -Compress
