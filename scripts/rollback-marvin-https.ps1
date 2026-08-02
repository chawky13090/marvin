[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runtime = Join-Path $Root 'runtime\https'
$Caddy = Join-Path $Runtime 'caddy.exe'
$Config = Join-Path $Runtime 'caddy.json'
$ServiceScript = Join-Path $PSScriptRoot 'manage-marvin-https-service.ps1'
$UntrustScript = Join-Path $PSScriptRoot 'untrust-marvin-https.ps1'

if (-not $PSCmdlet.ShouldProcess(
        $Runtime,
        'Arrêter le service, révoquer exactement les autorités Marvin et retirer le runtime HTTPS'
    )) {
    exit 0
}

$Service = Get-Service -Name 'MarvinHttpsGateway' -ErrorAction SilentlyContinue
if ($null -ne $Service) {
    & $ServiceScript -Action Uninstall -Confirm:$false
}
if ((Test-Path -LiteralPath $Caddy) -and (Test-Path -LiteralPath $Config)) {
    & $Caddy stop --config $Config 2>$null
}

# Révoquer avant de supprimer la clé publique et l'état qui permettent une suppression exacte.
foreach ($Scope in @('CurrentUser', 'LocalMachine')) {
    $StorePath = "Cert:\$Scope\Root"
    $TrustStatePath = Join-Path $Runtime 'trust-state.json'
    if (Test-Path -LiteralPath $TrustStatePath -PathType Leaf) {
        $TrustState = Get-Content -Raw -LiteralPath $TrustStatePath | ConvertFrom-Json
        $Thumbprint = [string]$TrustState.thumbprint
        $Present = $null -ne (Get-ChildItem -LiteralPath $StorePath |
            Where-Object { $_.Thumbprint -eq $Thumbprint } |
            Select-Object -First 1)
        if ($Present) {
            & $UntrustScript -Scope $Scope -Confirm:$false
        }
    }
}

Remove-Item -LiteralPath $Runtime -Recurse -Force -ErrorAction SilentlyContinue
