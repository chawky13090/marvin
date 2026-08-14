[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [switch]$RemoveData,
    [switch]$KeepSearXngContainer
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Marker = Join-Path $ProjectRoot 'runtime\install\state.json'
$LocalAppData = [IO.Path]::GetFullPath([Environment]::GetFolderPath('LocalApplicationData'))
if (-not (Test-Path -LiteralPath $Marker -PathType Leaf)) { throw 'Marqueur d installation Marvin absent; suppression automatique refusee.' }
if ($ProjectRoot -eq [IO.Path]::GetPathRoot($ProjectRoot) -or $ProjectRoot.Length -lt ($LocalAppData.Length + 4)) {
    throw 'Racine Marvin dangereuse; suppression refusee.'
}

if (-not $PSCmdlet.ShouldProcess($ProjectRoot, $(if ($RemoveData) { 'Desinstaller Marvin et supprimer ses donnees' } else { 'Desinstaller Marvin et preserver ses donnees' }))) { exit 0 }

$Stop = Join-Path $PSScriptRoot 'stop-marvin.ps1'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Stop -AllowActiveWorkInterruption
if ($LASTEXITCODE -ne 0) { throw 'Marvin ne peut pas etre arrete proprement.' }

Unregister-ScheduledTask -TaskName 'Marvin - Demarrage automatique' -Confirm:$false -ErrorAction SilentlyContinue
foreach ($Name in @('Marvin - Frontend', 'Marvin - Backend', 'Marvin - HTTPS')) {
    Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
}
if (-not $KeepSearXngContainer -and (Get-Command docker.exe -ErrorAction SilentlyContinue)) {
    & docker.exe rm -f marvin-searxng 2>$null | Out-Null
}
foreach ($Shortcut in @('Marvin.lnk', 'Desinstaller Marvin.lnk')) {
    Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)) $Shortcut) -Force -ErrorAction SilentlyContinue
}

$PreservedData = $null
if (-not $RemoveData -and (Test-Path -LiteralPath (Join-Path $ProjectRoot 'data') -PathType Container)) {
    $PreserveRoot = Join-Path $LocalAppData 'Marvin\PreservedData'
    New-Item -ItemType Directory -Path $PreserveRoot -Force | Out-Null
    $PreservedData = Join-Path $PreserveRoot (Get-Date -Format 'yyyyMMdd-HHmmss')
    Move-Item -LiteralPath (Join-Path $ProjectRoot 'data') -Destination $PreservedData
}

$CleanupScript = Join-Path $env:TEMP ("marvin-uninstall-$PID.ps1")
$QuotedRoot = $ProjectRoot.Replace("'", "''")
$Cleanup = @"
Start-Sleep -Seconds 3
`$Target = [IO.Path]::GetFullPath('$QuotedRoot')
if (`$Target -eq [IO.Path]::GetPathRoot(`$Target) -or `$Target.Length -lt 12) { exit 2 }
Remove-Item -LiteralPath `$Target -Recurse -Force
Remove-Item -LiteralPath `$MyInvocation.MyCommand.Path -Force
"@
[IO.File]::WriteAllText($CleanupScript, $Cleanup, [Text.UTF8Encoding]::new($false))
Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $CleanupScript) -WindowStyle Hidden | Out-Null

[ordered]@{
    success = $true
    removal_scheduled = $true
    data_removed = [bool]$RemoveData
    preserved_data = $PreservedData
    shared_system_runtimes_removed = $false
} | ConvertTo-Json -Depth 5
