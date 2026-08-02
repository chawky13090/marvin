[CmdletBinding()]
param(
    [ValidateRange(443, 65535)]
    [int]$Port = 8443
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runtime = Join-Path $Root 'runtime\https'
$Data = Join-Path $Runtime 'data'
$Template = Join-Path $Root 'config\Caddyfile.marvin'
$Output = Join-Path $Runtime 'caddy.json'

New-Item -ItemType Directory -Path $Runtime, $Data -Force | Out-Null

$Names = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
[void]$Names.Add('localhost')
[void]$Names.Add('127.0.0.1')
[void]$Names.Add($env:COMPUTERNAME)
$DefaultRoute = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Sort-Object RouteMetric, InterfaceMetric |
    Select-Object -First 1
if ($null -ne $DefaultRoute) {
    Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $DefaultRoute.InterfaceIndex -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notin @('0.0.0.0', '127.0.0.1') } |
        Select-Object -First 1 |
        ForEach-Object { [void]$Names.Add($_.IPAddress) }
}

$Origins = ($Names | Sort-Object | ForEach-Object { "https://$($_):$Port" }) -join ', '
$env:MARVIN_HTTPS_ORIGINS = $Origins
$env:MARVIN_CADDY_DATA = ($Data -replace '\\', '/')

$Caddy = Join-Path $Runtime 'caddy.exe'
if (-not (Test-Path -LiteralPath $Caddy)) {
    throw 'Caddy absent. Exécutez install-marvin-https.ps1.'
}
$Adapted = (& $Caddy adapt --config $Template --adapter caddyfile --pretty) -join [Environment]::NewLine
[IO.File]::WriteAllText($Output, $Adapted, [Text.UTF8Encoding]::new($false))

$State = [ordered]@{
    schema_version = 1
    enabled = $true
    port = $Port
    origins = @($Names | Sort-Object | ForEach-Object { "https://$($_):$Port" })
    config_path = $Output
}
[IO.File]::WriteAllText(
    (Join-Path $Runtime 'state.json'),
    ($State | ConvertTo-Json -Depth 4),
    [Text.UTF8Encoding]::new($false)
)
$State
