[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('CurrentUser', 'LocalMachine')]
    [string]$Scope = 'CurrentUser'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Certificate = Join-Path $Root 'runtime\https\data\pki\authorities\local\root.crt'
if (-not (Test-Path -LiteralPath $Certificate)) {
    throw 'Autorité Marvin absente. Démarrez une première fois la passerelle HTTPS.'
}

$Fingerprint = (Get-FileHash -LiteralPath $Certificate -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Empreinte SHA-256 de l'autorité Marvin : $Fingerprint"
if ($PSCmdlet.ShouldProcess("Cert:\$Scope\Root", 'Approuver uniquement l’autorité HTTPS de cette installation Marvin')) {
    $Arguments = @('-addstore', 'Root', $Certificate)
    if ($Scope -eq 'CurrentUser') {
        $Arguments = @('-user') + $Arguments
    }
    & certutil.exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Échec de l'import du certificat racine Marvin ($LASTEXITCODE)."
    }
}
