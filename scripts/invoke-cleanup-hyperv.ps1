Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$cleanup = Join-Path $PSScriptRoot 'cleanup-hyperv-orphan-cache-admin.ps1'
if (-not (Test-Path -LiteralPath $cleanup -PathType Leaf)) {
    throw "Script de nettoyage introuvable : $cleanup"
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    & $cleanup -Confirmed
    exit 0
}
$argumentLine = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "{0}" -Confirmed' -f $cleanup
$process = Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -PassThru -ArgumentList $argumentLine
exit $process.ExitCode
