[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$ZipPath,
    [string]$OutputDirectory = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$SecurityModule = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1'
if (-not (Test-Path -LiteralPath $SecurityModule -PathType Leaf)) { throw 'Module de securite PowerShell Windows introuvable.' }
Import-Module -Name $SecurityModule -Force -ErrorAction Stop
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$ZipPath = [IO.Path]::GetFullPath($ZipPath)
if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) { throw 'ZIP Marvin source absent.' }
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { $OutputDirectory = Join-Path $ProjectRoot 'dist' }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$IExpress = Join-Path $env:SystemRoot 'System32\iexpress.exe'
if (-not (Test-Path -LiteralPath $IExpress -PathType Leaf)) { throw 'IExpress Windows est indisponible.' }

function Get-Sha256Hex([string]$Path) {
    $Stream = [System.IO.File]::OpenRead($Path)
    $Hasher = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($Hasher.ComputeHash($Stream))).Replace('-', '').ToLowerInvariant() }
    finally { $Hasher.Dispose(); $Stream.Dispose() }
}

function Get-CertificateWithRetry([string]$Thumbprint, [int]$Attempts = 5) {
    if ([string]::IsNullOrWhiteSpace($Thumbprint)) { return $null }
    for ($Attempt = 1; $Attempt -le $Attempts; $Attempt++) {
        $Certificate = Get-ChildItem -LiteralPath 'Cert:\CurrentUser\My' -ErrorAction SilentlyContinue |
            Where-Object { $_.Thumbprint -eq $Thumbprint } |
            Select-Object -First 1
        if ($null -ne $Certificate) { return $Certificate }
        if ($Attempt -lt $Attempts) { Start-Sleep -Milliseconds 400 }
    }
    return $null
}

function Import-PrivateCertificateBackup([string]$PfxPath, [string]$PasswordPath) {
    if (-not (Test-Path -LiteralPath $PfxPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $PasswordPath -PathType Leaf)) { return $null }
    $ProtectedPassword = Get-Content -LiteralPath $PasswordPath -Raw -Encoding UTF8
    $SecurePassword = ConvertTo-SecureString -String $ProtectedPassword
    return [Security.Cryptography.X509Certificates.X509Certificate2]::new(
        $PfxPath,
        $SecurePassword,
        [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable
    )
}

$VersionText = Get-Content -LiteralPath (Join-Path $ProjectRoot 'backend\app_version.py') -Raw -Encoding UTF8
$VersionMatch = [regex]::Match($VersionText, 'APP_VERSION\s*=\s*["'']([^"'']+)["'']')
if (-not $VersionMatch.Success) { throw 'Version Marvin introuvable.' }
$Version = $VersionMatch.Groups[1].Value
$GitCommit = (& git -C $ProjectRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $GitCommit -notmatch '^[0-9a-f]{40}$') { throw 'Commit Git courant introuvable.' }

Add-Type -AssemblyName System.IO.Compression.FileSystem
$Archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
try {
    # ZipArchive conserve parfois les separateurs Windows produits par
    # Compress-Archive. Le nom doit rester strictement terminal et unique.
    $ManifestEntries = @($Archive.Entries | Where-Object { $_.FullName -match '(^|[\\/])package-manifest\.json$' })
    if ($ManifestEntries.Count -ne 1) { throw 'Le ZIP doit contenir un unique package-manifest.json.' }
    $Reader = [IO.StreamReader]::new($ManifestEntries[0].Open(), [Text.Encoding]::UTF8, $true)
    try { $PackageManifest = $Reader.ReadToEnd() | ConvertFrom-Json } finally { $Reader.Dispose() }
} finally {
    $Archive.Dispose()
}
if ([string]$PackageManifest.product_version -ne $Version) { throw 'La version du ZIP ne correspond pas a la version Marvin courante.' }
if ([string]$PackageManifest.source_commit -ne $GitCommit) { throw 'Le ZIP ne provient pas du commit Git courant.' }

$SigningRoot = Join-Path $env:LOCALAPPDATA 'Marvin\signing-private'
New-Item -ItemType Directory -Path $SigningRoot -Force | Out-Null
$CurrentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $SigningRoot '/inheritance:r' '/grant:r' "*$CurrentSid`:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Durcissement ACL du coffre de signature impossible.' }
$IdentityPath = Join-Path $SigningRoot 'identity.json'
$Certificate = $null
$RootCertificate = $null
if (Test-Path -LiteralPath $IdentityPath -PathType Leaf) {
    $Identity = Get-Content -LiteralPath $IdentityPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$Identity.schema_version -eq '2') {
        $Certificate = Get-CertificateWithRetry -Thumbprint ([string]$Identity.signer_thumbprint)
        $RootCertificate = Get-CertificateWithRetry -Thumbprint ([string]$Identity.root_thumbprint)
        $BackupPasswordPath = Join-Path $SigningRoot 'marvin-private-signing-backup-password.dpapi'
        if ($null -eq $Certificate) {
            $Certificate = Import-PrivateCertificateBackup -PfxPath (Join-Path $SigningRoot 'marvin-private-signing-backup.pfx') -PasswordPath $BackupPasswordPath
        }
        if ($null -eq $RootCertificate) {
            $RootCertificate = Import-PrivateCertificateBackup -PfxPath (Join-Path $SigningRoot 'marvin-private-root-backup.pfx') -PasswordPath $BackupPasswordPath
        }
        if ($null -eq $Certificate -or -not $Certificate.HasPrivateKey -or $Certificate.NotAfter -le (Get-Date).AddDays(30)) {
            $Found = $null -ne $Certificate
            $HasPrivateKey = $Found -and $Certificate.HasPrivateKey
            $NotAfter = if ($Found) { $Certificate.NotAfter.ToUniversalTime().ToString('o') } else { 'absent' }
            throw "Certificat signataire Marvin inutilisable (present=$Found; cle_privee=$HasPrivateKey; expiration=$NotAfter)."
        }
        if ($null -eq $RootCertificate -or -not $RootCertificate.HasPrivateKey -or $RootCertificate.NotAfter -le (Get-Date).AddDays(90)) { throw 'Autorite privee Marvin absente ou proche de l expiration.' }
    }
}
if ($null -eq $Certificate -or $null -eq $RootCertificate) {
    $RootCertificate = New-SelfSignedCertificate -Type Custom -Subject 'CN=Marvin Private Root CA, O=Chaouki BOUSSAYRI' -CertStoreLocation 'Cert:\CurrentUser\My' -KeyAlgorithm RSA -KeyLength 4096 -HashAlgorithm SHA256 -KeyExportPolicy Exportable -KeyUsage CertSign,CRLSign,DigitalSignature -TextExtension @('2.5.29.19={critical}{text}ca=1&pathlength=0') -NotAfter (Get-Date).AddYears(10)
    $Certificate = New-SelfSignedCertificate -Type CodeSigningCert -Subject 'CN=Marvin Private Publisher, O=Chaouki BOUSSAYRI' -Signer $RootCertificate -CertStoreLocation 'Cert:\CurrentUser\My' -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -KeyExportPolicy Exportable -NotAfter (Get-Date).AddYears(3)
    $PasswordBytes = New-Object byte[] 32
    $Random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $Random.GetBytes($PasswordBytes) } finally { $Random.Dispose() }
    $PasswordText = [Convert]::ToBase64String($PasswordBytes)
    $SecurePassword = ConvertTo-SecureString -String $PasswordText -AsPlainText -Force
    Export-PfxCertificate -Cert $Certificate -FilePath (Join-Path $SigningRoot 'marvin-private-signing-backup.pfx') -Password $SecurePassword -Force | Out-Null
    Export-PfxCertificate -Cert $RootCertificate -FilePath (Join-Path $SigningRoot 'marvin-private-root-backup.pfx') -Password $SecurePassword -Force | Out-Null
    $ProtectedPassword = ConvertFrom-SecureString -SecureString $SecurePassword
    [IO.File]::WriteAllText((Join-Path $SigningRoot 'marvin-private-signing-backup-password.dpapi'), $ProtectedPassword, [Text.UTF8Encoding]::new($false))
    $Identity = [ordered]@{ schema_version = 2; signer_thumbprint = $Certificate.Thumbprint.ToUpperInvariant(); signer_subject = $Certificate.Subject; signer_not_after = $Certificate.NotAfter.ToUniversalTime().ToString('o'); root_thumbprint = $RootCertificate.Thumbprint.ToUpperInvariant(); root_subject = $RootCertificate.Subject; root_not_after = $RootCertificate.NotAfter.ToUniversalTime().ToString('o'); scope = 'private-deployment-only' }
    [IO.File]::WriteAllText($IdentityPath, ($Identity | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
}

$BuildRoot = Join-Path $env:TEMP ('marvin-private-package-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $BuildRoot | Out-Null
try {
    $SourceZip = Join-Path $BuildRoot 'marvin-package.zip'
    Copy-Item -LiteralPath $ZipPath -Destination $SourceZip
    $ZipHash = Get-Sha256Hex -Path $SourceZip
    [IO.File]::WriteAllText("$SourceZip.sha256", "$ZipHash  marvin-package.zip`n", [Text.UTF8Encoding]::new($false))
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'launch-marvin-private-package.ps1') -Destination (Join-Path $BuildRoot 'launch-marvin-private-package.ps1')
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    $ExePath = Join-Path $OutputDirectory "Marvin-Setup-Private-v$Version.exe"
    $SedPath = Join-Path $BuildRoot 'package.sed'
    $Source = $BuildRoot.TrimEnd('\') + '\'
    $Sed = @"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=$ExePath
FriendlyName=Installation privee Marvin $Version
AppLaunched=powershell.exe -NoProfile -ExecutionPolicy Bypass -File launch-marvin-private-package.ps1
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
SourceFiles=SourceFiles
[Strings]
FILE0="marvin-package.zip"
FILE1="marvin-package.zip.sha256"
FILE2="launch-marvin-private-package.ps1"
[SourceFiles]
SourceFiles0=$Source
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
"@
    [IO.File]::WriteAllText($SedPath, $Sed, [Text.Encoding]::ASCII)
    if (Test-Path -LiteralPath $ExePath) { Remove-Item -LiteralPath $ExePath -Force }
    $Process = Start-Process -FilePath $IExpress -ArgumentList @('/N', '/Q', $SedPath) -Wait -PassThru
    if ($Process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $ExePath -PathType Leaf)) { throw "IExpress a echoue ($($Process.ExitCode))." }
    $Signature = Set-AuthenticodeSignature -LiteralPath $ExePath -Certificate $Certificate -HashAlgorithm SHA256 -IncludeChain All
    if ($Signature.Status -notin @('Valid', 'UnknownError')) { throw "Signature Authenticode impossible : $($Signature.Status)." }
    $Observed = Get-AuthenticodeSignature -LiteralPath $ExePath
    if ($null -eq $Observed.SignerCertificate -or $Observed.SignerCertificate.Thumbprint -ne $Certificate.Thumbprint) { throw 'Le signataire relu ne correspond pas a l identite Marvin.' }

    $PublicCertificate = Join-Path $OutputDirectory 'Marvin-Private-Publisher.cer'
    Export-Certificate -Cert $Certificate -FilePath $PublicCertificate -Force | Out-Null
    $CerHash = Get-Sha256Hex -Path $PublicCertificate
    [IO.File]::WriteAllText("$PublicCertificate.sha256", "$CerHash  Marvin-Private-Publisher.cer`n", [Text.UTF8Encoding]::new($false))
    $PublicRoot = Join-Path $OutputDirectory 'Marvin-Private-Root.cer'
    Export-Certificate -Cert $RootCertificate -FilePath $PublicRoot -Force | Out-Null
    $RootHash = Get-Sha256Hex -Path $PublicRoot
    [IO.File]::WriteAllText("$PublicRoot.sha256", "$RootHash  Marvin-Private-Root.cer`n", [Text.UTF8Encoding]::new($false))
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'trust-marvin-private-publisher.ps1') -Destination (Join-Path $OutputDirectory 'trust-marvin-private-publisher.ps1') -Force
    [IO.File]::WriteAllText((Join-Path $OutputDirectory 'FAIRE-CONFIANCE-A-MARVIN.bat'), "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%~dp0trust-marvin-private-publisher.ps1`" -Confirm`r`npause`r`n", [Text.Encoding]::ASCII)
    [IO.File]::WriteAllText((Join-Path $OutputDirectory 'RETIRER-CONFIANCE-MARVIN.bat'), "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%~dp0trust-marvin-private-publisher.ps1`" -Remove -Confirm`r`npause`r`n", [Text.Encoding]::ASCII)
    $ExeHash = Get-Sha256Hex -Path $ExePath
    [IO.File]::WriteAllText("$ExePath.sha256", "$ExeHash  $([IO.Path]::GetFileName($ExePath))`n", [Text.UTF8Encoding]::new($false))
    [ordered]@{ success = $true; package = $ExePath; sha256 = $ExeHash; signer_subject = $Certificate.Subject; signer_thumbprint = $Certificate.Thumbprint.ToUpperInvariant(); certificate_sha256 = $CerHash; root_subject = $RootCertificate.Subject; root_thumbprint = $RootCertificate.Thumbprint.ToUpperInvariant(); root_certificate_sha256 = $RootHash; trust_scope = 'LocalMachine\\Root + LocalMachine\\TrustedPublisher'; requires_uac = $true; public_trust = $false; product_version = $Version } | ConvertTo-Json -Depth 4
} finally {
    if (Test-Path -LiteralPath $BuildRoot) { Remove-Item -LiteralPath $BuildRoot -Recurse -Force }
}
