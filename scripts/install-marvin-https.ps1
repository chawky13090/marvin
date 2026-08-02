[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateRange(443, 65535)]
    [int]$Port = 8443,
    [switch]$Start
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$CaddyVersion = '2.11.4'
$ExpectedSha512 = 'cd5ccfd86a4b40732cf715890d0dca5bf3f63adefec5a7914de85adf240c60ce7e5d2791631b88ef9758e46b23bb1730e020b9c5d696889740b284ffd4788e35'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runtime = Join-Path $Root 'runtime\https'
$Archive = Join-Path $Runtime "caddy_$CaddyVersion.zip"
$Caddy = Join-Path $Runtime 'caddy.exe'
$Download = "https://github.com/caddyserver/caddy/releases/download/v$CaddyVersion/caddy_${CaddyVersion}_windows_amd64.zip"

if (-not [Environment]::Is64BitOperatingSystem) {
    throw 'La passerelle HTTPS Marvin exige Windows x64 dans cette version.'
}

if ($PSCmdlet.ShouldProcess($Runtime, 'Installer la passerelle HTTPS Marvin')) {
    New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
    if (-not (Test-Path -LiteralPath $Caddy)) {
        Invoke-WebRequest -Uri $Download -OutFile $Archive -UseBasicParsing
        $Observed = (Get-FileHash -LiteralPath $Archive -Algorithm SHA512).Hash.ToLowerInvariant()
        if ($Observed -ne $ExpectedSha512) {
            Remove-Item -LiteralPath $Archive -Force -ErrorAction SilentlyContinue
            throw "Intégrité Caddy invalide. SHA-512 observé: $Observed"
        }
        Expand-Archive -LiteralPath $Archive -DestinationPath $Runtime -Force
        Remove-Item -LiteralPath $Archive -Force
    }

    & $Caddy version | Out-Null
    & (Join-Path $PSScriptRoot 'write-marvin-https-config.ps1') -Port $Port

    if ($Start) {
        & (Join-Path $PSScriptRoot 'start-marvin-https.ps1') -Port $Port
    }
}
