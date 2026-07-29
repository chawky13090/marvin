[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runtime = Join-Path $Root 'runtime\https'
$Caddy = Join-Path $Runtime 'caddy.exe'
$Config = Join-Path $Runtime 'caddy.json'

if ((Test-Path -LiteralPath $Caddy) -and (Test-Path -LiteralPath $Config)) {
    & $Caddy stop --config $Config 2>$null
}
if ($PSCmdlet.ShouldProcess($Runtime, 'Désactiver et retirer le runtime HTTPS local')) {
    Remove-Item -LiteralPath $Runtime -Recurse -Force -ErrorAction SilentlyContinue
}
