[CmdletBinding()]
param(
    [ValidateRange(443, 65535)]
    [int]$Port = 8443
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runtime = Join-Path $Root 'runtime\https'
$Caddy = Join-Path $Runtime 'caddy.exe'
$Config = Join-Path $Runtime 'caddy.json'

& (Join-Path $PSScriptRoot 'write-marvin-https-config.ps1') -Port $Port | Out-Null
& $Caddy validate --config $Config
& $Caddy run --config $Config
