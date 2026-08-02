[CmdletBinding(SupportsShouldProcess)]
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
if (-not (Test-Path -LiteralPath $Certificate -PathType Leaf)) {
    throw 'Autorité Marvin absente. Démarrez une première fois la passerelle HTTPS.'
}

$CertificateObject = [Security.Cryptography.X509Certificates.X509Certificate2]::new($Certificate)
try {
    $Thumbprint = $CertificateObject.Thumbprint.ToUpperInvariant()
    $Sha256 = (Get-FileHash -LiteralPath $Certificate -Algorithm SHA256).Hash.ToLowerInvariant()
} finally {
    $CertificateObject.Dispose()
}

$StorePath = "Cert:\$Scope\Root"
$AlreadyTrusted = $null -ne (Get-ChildItem -LiteralPath $StorePath |
    Where-Object { $_.Thumbprint -eq $Thumbprint } |
    Select-Object -First 1)
if (-not $AlreadyTrusted -and $PSCmdlet.ShouldProcess(
        $StorePath,
        "Approuver uniquement l'autorité HTTPS Marvin $Thumbprint"
    )) {
    $Arguments = @('-f', '-silent', '-addstore', 'Root', $Certificate)
    if ($Scope -eq 'CurrentUser') { $Arguments = @('-user') + $Arguments }
    & certutil.exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Échec de l'import du certificat racine Marvin ($LASTEXITCODE)."
    }
}

$Verified = $null -ne (Get-ChildItem -LiteralPath $StorePath |
    Where-Object { $_.Thumbprint -eq $Thumbprint } |
    Select-Object -First 1)
if (-not $Verified) {
    throw "L'autorité $Thumbprint n'est pas présente dans $StorePath après import."
}

$ExistingScopes = @()
if (Test-Path -LiteralPath $TrustStatePath -PathType Leaf) {
    $Previous = Get-Content -Raw -LiteralPath $TrustStatePath | ConvertFrom-Json
    if ($Previous.thumbprint -eq $Thumbprint) { $ExistingScopes = @($Previous.scopes) }
}
$State = [ordered]@{
    schema_version = 1
    thumbprint = $Thumbprint
    sha256 = $Sha256
    scopes = @($ExistingScopes + $Scope | Sort-Object -Unique)
    updated_at = [DateTimeOffset]::UtcNow.ToString('o')
}
$Temporary = "$TrustStatePath.tmp"
[IO.File]::WriteAllText($Temporary, ($State | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $Temporary -Destination $TrustStatePath -Force
Write-MarvinHttpsEvent -Action 'trust-authority' -Result 'success' -Context @{
    scope = $Scope
    already_trusted = $AlreadyTrusted
}

[pscustomobject]@{
    scope = $Scope
    thumbprint = $Thumbprint
    sha256 = $Sha256
    already_trusted = $AlreadyTrusted
    verified = $true
}
