[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [ValidateSet('CurrentUser', 'LocalMachine')]
    [string]$Scope = 'CurrentUser'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'marvin-https-logging.ps1')
$Runtime = Join-Path $Root 'runtime\https'
$Certificate = Join-Path $Runtime 'data\pki\authorities\local\root.crt'
$TrustStatePath = Join-Path $Runtime 'trust-state.json'
$Thumbprint = $null
if (Test-Path -LiteralPath $TrustStatePath -PathType Leaf) {
    $TrustState = Get-Content -Raw -LiteralPath $TrustStatePath | ConvertFrom-Json
    $Thumbprint = [string]$TrustState.thumbprint
}
if ([string]::IsNullOrWhiteSpace($Thumbprint) -and (Test-Path -LiteralPath $Certificate -PathType Leaf)) {
    $CertificateObject = [Security.Cryptography.X509Certificates.X509Certificate2]::new($Certificate)
    try { $Thumbprint = $CertificateObject.Thumbprint } finally { $CertificateObject.Dispose() }
}
if ([string]::IsNullOrWhiteSpace($Thumbprint)) {
    throw 'Empreinte de l’autorité Marvin introuvable; révocation exacte impossible.'
}

$Thumbprint = $Thumbprint.ToUpperInvariant()
$StorePath = "Cert:\$Scope\Root"
$Present = $null -ne (Get-ChildItem -LiteralPath $StorePath |
    Where-Object { $_.Thumbprint -eq $Thumbprint } |
    Select-Object -First 1)
if ($Present) {
    if (-not $PSCmdlet.ShouldProcess(
            $StorePath,
            "Révoquer uniquement l'autorité HTTPS Marvin $Thumbprint"
        )) {
        Write-MarvinHttpsEvent -Action 'untrust-authority' -Result 'planned' -Context @{ scope = $Scope }
        [pscustomobject]@{ scope = $Scope; thumbprint = $Thumbprint; was_present = $true; revoked = $false }
        exit 0
    }
    # Windows exige sa propre confirmation pour retirer une racine de confiance.
    # Ne pas la contourner : elle complète le ShouldProcess PowerShell.
    $Arguments = @('-delstore', 'Root', $Thumbprint)
    if ($Scope -eq 'CurrentUser') { $Arguments = @('-user') + $Arguments }
    & certutil.exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Échec de la révocation du certificat Marvin ($LASTEXITCODE)."
    }
}

$StillPresent = $null -ne (Get-ChildItem -LiteralPath $StorePath |
    Where-Object { $_.Thumbprint -eq $Thumbprint } |
    Select-Object -First 1)
if ($StillPresent) { throw "L'autorité $Thumbprint reste présente dans $StorePath." }

if (Test-Path -LiteralPath $TrustStatePath -PathType Leaf) {
    $TrustState = Get-Content -Raw -LiteralPath $TrustStatePath | ConvertFrom-Json
    $State = [ordered]@{
        schema_version = 1
        thumbprint = [string]$TrustState.thumbprint
        sha256 = [string]$TrustState.sha256
        scopes = @($TrustState.scopes | Where-Object { $_ -ne $Scope })
        updated_at = [DateTimeOffset]::UtcNow.ToString('o')
    }
    $Temporary = "$TrustStatePath.tmp"
    [IO.File]::WriteAllText($Temporary, ($State | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $Temporary -Destination $TrustStatePath -Force
}
Write-MarvinHttpsEvent -Action 'untrust-authority' -Result 'success' -Context @{
    scope = $Scope
    was_present = $Present
}
[pscustomobject]@{ scope = $Scope; thumbprint = $Thumbprint; was_present = $Present; revoked = $true }
