[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [switch]$Remove,
    [switch]$Elevated
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
$IsAdministrator = $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsAdministrator) {
    if ($Elevated) { throw 'Elevation administrateur requise pour le magasin de confiance machine.' }
    $Arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Elevated', '-Confirm')
    if ($Remove) { $Arguments += '-Remove' }
    $Process = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $Arguments -Wait -PassThru
    exit $Process.ExitCode
}

function Get-Sha256Hex([string]$Path) {
    $Hasher = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($Hasher.ComputeHash([IO.File]::ReadAllBytes($Path)))).Replace('-', '').ToLowerInvariant() }
    finally { $Hasher.Dispose() }
}

$PublisherPath = Join-Path $PSScriptRoot 'Marvin-Private-Publisher.cer'
$RootPath = Join-Path $PSScriptRoot 'Marvin-Private-Root.cer'
foreach ($Path in @($PublisherPath, $RootPath)) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Certificat public absent : $Path" }
    $HashPath = "$Path.sha256"
    if (-not (Test-Path -LiteralPath $HashPath -PathType Leaf)) { throw "Empreinte absente : $HashPath" }
    $Expected = ((Get-Content -LiteralPath $HashPath -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    $Actual = Get-Sha256Hex -Path $Path
    if ($Expected -notmatch '^[0-9a-f]{64}$' -or $Actual -ne $Expected) { throw "Empreinte invalide : $Path" }
}

$Publisher = [Security.Cryptography.X509Certificates.X509Certificate2]::new($PublisherPath)
$Root = [Security.Cryptography.X509Certificates.X509Certificate2]::new($RootPath)
$Stores = @()
try {
    if ($Publisher.Issuer -ne $Root.Subject) { throw 'Le certificat editeur n est pas emis par l autorite Marvin fournie.' }
    $Mappings = @(
        [pscustomobject]@{ Name = 'Root'; Certificate = $Root },
        [pscustomobject]@{ Name = 'TrustedPublisher'; Certificate = $Publisher }
    )
    foreach ($Mapping in $Mappings) {
        $Store = [Security.Cryptography.X509Certificates.X509Store]::new($Mapping.Name, 'LocalMachine')
        $Store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
        $Stores += $Store
    }
    if ($Remove) {
        if ($PSCmdlet.ShouldProcess($Root.Thumbprint, 'Retirer l autorite et l editeur Marvin de la confiance machine')) {
            for ($Index = 0; $Index -lt $Mappings.Count; $Index++) {
                $Thumbprint = $Mappings[$Index].Certificate.Thumbprint
                foreach ($Item in @($Stores[$Index].Certificates | Where-Object Thumbprint -eq $Thumbprint)) { $Stores[$Index].Remove($Item) }
            }
            Write-Host 'Confiance privee Marvin retiree.'
        }
        return
    }
    Write-Host "Autorite privee : $($Root.Subject)"
    Write-Host "Empreinte autorite : $($Root.Thumbprint.ToUpperInvariant())"
    Write-Host "Editeur prive : $($Publisher.Subject)"
    Write-Host "Empreinte editeur : $($Publisher.Thumbprint.ToUpperInvariant())"
    if ($PSCmdlet.ShouldProcess($Publisher.Thumbprint, 'Approuver l autorite Marvin et cet editeur pour ce poste Windows')) {
        for ($Index = 0; $Index -lt $Mappings.Count; $Index++) {
            $Certificate = $Mappings[$Index].Certificate
            if (@($Stores[$Index].Certificates | Where-Object Thumbprint -eq $Certificate.Thumbprint).Count -eq 0) { $Stores[$Index].Add($Certificate) }
        }
        Write-Host 'Autorite et editeur prives Marvin approuves pour ce poste Windows.'
    }
} finally {
    foreach ($Store in $Stores) { $Store.Close() }
    $Publisher.Dispose()
    $Root.Dispose()
}
