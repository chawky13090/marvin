[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstallRoot = '',
    [switch]$NoStart,
    [switch]$SkipModels,
    [switch]$SkipOptional,
    [ValidateSet('Full', 'Core')]
    [string]$DeploymentProfile = 'Full',
    [switch]$AcceptDockerDesktopLicense
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$DryRunRequested = [bool]$WhatIfPreference
$WhatIfPreference = $false

function Get-Sha256Hex([string]$Path) {
    $Stream = [System.IO.File]::OpenRead($Path)
    $Hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Bytes = $Hasher.ComputeHash($Stream)
        return ([System.BitConverter]::ToString($Bytes)).Replace('-', '').ToLowerInvariant()
    } finally {
        $Hasher.Dispose()
        $Stream.Dispose()
    }
}

$PackageRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$ManifestPath = Join-Path $PackageRoot 'package-manifest.json'
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { throw 'Manifest de paquet absent.' }
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([int]$Manifest.schema_version -ne 1) { throw 'Version de manifest de paquet non supportee.' }
$PayloadPath = Join-Path $PackageRoot ([string]$Manifest.payload.file)
if (-not (Test-Path -LiteralPath $PayloadPath -PathType Leaf)) { throw 'Payload Marvin absent.' }
$ObservedHash = Get-Sha256Hex -Path $PayloadPath
if ($ObservedHash -ne ([string]$Manifest.payload.sha256).ToLowerInvariant()) { throw 'Integrite du payload Marvin invalide.' }

if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\Marvin'
}
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$LocalAppData = [IO.Path]::GetFullPath([Environment]::GetFolderPath('LocalApplicationData'))
if ($InstallRoot -eq [IO.Path]::GetPathRoot($InstallRoot) -or $InstallRoot.Length -lt ($LocalAppData.Length + 4)) {
    throw 'Racine d installation refusee car trop large ou dangereuse.'
}
if ($InstallRoot -eq $PackageRoot -or $InstallRoot.StartsWith($PackageRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'La cible d installation doit etre distincte du paquet extrait.'
}
if ($DryRunRequested) {
    Write-Host "Le payload verifie serait installe dans $InstallRoot."
    exit 0
}

$Parent = Split-Path -Parent $InstallRoot
$Staging = Join-Path $Parent ('.Marvin.stage-' + [guid]::NewGuid().ToString('N'))
$Backup = Join-Path $Parent ('Marvin.rollback-' + (Get-Date -Format 'yyyyMMddHHmmss'))
$ExistingMetadata = Join-Path $InstallRoot 'runtime\install\package.json'
$SamePackage = $false
if (Test-Path -LiteralPath $ExistingMetadata -PathType Leaf) {
    try { $SamePackage = ([string](Get-Content -LiteralPath $ExistingMetadata -Raw | ConvertFrom-Json).source_commit) -eq [string]$Manifest.source_commit } catch {}
}

function Restore-PreviousInstall {
    if (-not (Test-Path -LiteralPath $Backup -PathType Container)) { return }
    foreach ($Name in @('data', 'runtime', '.env.local')) {
        $Current = Join-Path $InstallRoot $Name
        if (Test-Path -LiteralPath $Current) { Move-Item -LiteralPath $Current -Destination (Join-Path $Backup $Name) -Force }
    }
    if (Test-Path -LiteralPath $InstallRoot) { Remove-Item -LiteralPath $InstallRoot -Recurse -Force }
    Move-Item -LiteralPath $Backup -Destination $InstallRoot
}

function Stop-InstalledLauncher {
    # Les anciens lanceurs peuvent rester sur pause après l'arrêt des serveurs.
    # Leur répertoire courant verrouille alors le renommage Windows du dossier.
    # Le chemin exact et le nom cmd.exe excluent les autres terminaux utilisateur.
    $Launcher = Join-Path $InstallRoot 'start.bat'
    $Pattern = [regex]::Escape($Launcher) + '(?=["\s]|$)'
    foreach ($Process in @(Get-CimInstance Win32_Process -Filter "Name='cmd.exe'")) {
        if ([string]$Process.CommandLine -notmatch $Pattern) { continue }
        $Handle = Get-Process -Id $Process.ProcessId -ErrorAction SilentlyContinue
        if ($null -eq $Handle) { continue }
        try {
            Stop-Process -Id $Handle.Id -Force -ErrorAction Stop
            if (-not $Handle.WaitForExit(10000)) { throw 'Le lanceur precedent reste actif.' }
        } finally { $Handle.Dispose() }
    }
}

try {
    if (-not $SamePackage) {
        New-Item -ItemType Directory -Path $Parent -Force | Out-Null
        Expand-Archive -LiteralPath $PayloadPath -DestinationPath $Staging -Force
        foreach ($Required in @($Manifest.required_files)) {
            $RequiredPath = Join-Path $Staging ([string]$Required).Replace('/', '\')
            if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) { throw "Payload incomplet : $Required" }
        }
        if (Test-Path -LiteralPath $InstallRoot -PathType Container) {
            $Stop = Join-Path $InstallRoot 'scripts\stop-marvin.ps1'
            if (Test-Path -LiteralPath $Stop) {
                & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Stop -AllowActiveWorkInterruption
                if ($LASTEXITCODE -ne 0) { throw 'L ancienne installation Marvin ne peut pas etre arretee.' }
            }
            Stop-InstalledLauncher
            Move-Item -LiteralPath $InstallRoot -Destination $Backup
            foreach ($Name in @('data', 'runtime', '.env.local')) {
                $Old = Join-Path $Backup $Name
                if (Test-Path -LiteralPath $Old) { Move-Item -LiteralPath $Old -Destination (Join-Path $Staging $Name) }
            }
        }
        Move-Item -LiteralPath $Staging -Destination $InstallRoot
        $MetadataPath = Join-Path $InstallRoot 'runtime\install\package.json'
        New-Item -ItemType Directory -Path (Split-Path -Parent $MetadataPath) -Force | Out-Null
        $Metadata = [ordered]@{
            schema_version = 1
            source_commit = [string]$Manifest.source_commit
            product_version = [string]$Manifest.product_version
            installed_at = (Get-Date).ToUniversalTime().ToString('o')
            package_payload_sha256 = $ObservedHash
            rollback_path = if (Test-Path -LiteralPath $Backup) { $Backup } else { $null }
        }
        [IO.File]::WriteAllText($MetadataPath, ($Metadata | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
    }

    $Installer = Join-Path $InstallRoot 'scripts\install-marvin-oneclick.ps1'
    $Arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $Installer))
    if ($NoStart) { $Arguments += '-NoStart' }
    if ($SkipModels) { $Arguments += '-SkipModels' }
    if ($SkipOptional) { $Arguments += '-SkipOptional' }
    $Arguments += @('-DeploymentProfile', $DeploymentProfile)
    if ($AcceptDockerDesktopLicense) { $Arguments += '-AcceptDockerDesktopLicense' }
    $Process = Start-Process -FilePath 'powershell.exe' -ArgumentList $Arguments -WorkingDirectory $InstallRoot -Wait -PassThru
    if ($Process.ExitCode -ne 0) {
        if (Test-Path -LiteralPath $Backup) { Restore-PreviousInstall }
        throw "L installation des composants Marvin a echoue (code $($Process.ExitCode))."
    }
    Write-Host ''
    Write-Host "Marvin est installe dans : $InstallRoot" -ForegroundColor Green
    if (Test-Path -LiteralPath $Backup) { Write-Host "Rollback de code conserve : $Backup" }
    exit 0
} catch {
    if (Test-Path -LiteralPath $Staging) { Remove-Item -LiteralPath $Staging -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Error $_
    exit 1
}
