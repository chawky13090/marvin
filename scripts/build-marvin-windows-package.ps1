[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$OutputDirectory = '',
    [switch]$AllowDirtyTrackedTree
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$DryRunRequested = [bool]$WhatIfPreference
$WhatIfPreference = $false
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$BuildRoot = ''
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $ProjectRoot 'dist'
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)

if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { throw 'Git est requis pour produire un paquet depuis les octets suivis.' }
if ($DryRunRequested) {
    Write-Host "Le paquet serait construit depuis HEAD vers $OutputDirectory."
    exit 0
}
Push-Location $ProjectRoot
try {
    $TrackedStatus = @(& git status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) { throw 'Impossible de lire l etat Git.' }
    if ($TrackedStatus.Count -gt 0 -and -not $AllowDirtyTrackedTree) {
        throw 'Le worktree suivi doit etre propre. Committez les changements avant de creer le paquet.'
    }
    $Commit = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $Commit -notmatch '^[0-9a-f]{40}$') { throw 'Commit source Git invalide.' }
    $VersionText = Get-Content -LiteralPath (Join-Path $ProjectRoot 'backend\app_version.py') -Raw -Encoding UTF8
    $VersionMatch = [regex]::Match($VersionText, 'APP_VERSION\s*=\s*["'']([^"'']+)["'']')
    if (-not $VersionMatch.Success) { throw 'Version Marvin introuvable.' }
    $Version = $VersionMatch.Groups[1].Value
    $PackageName = "Marvin-Windows-v$Version"
    $BuildRoot = Join-Path $env:TEMP ("marvin-package-" + [guid]::NewGuid().ToString('N'))
    $PackageRoot = Join-Path $BuildRoot $PackageName
    New-Item -ItemType Directory -Path $PackageRoot -Force | Out-Null
    $PayloadPath = Join-Path $PackageRoot 'payload.zip'
    if ($PSCmdlet.ShouldProcess($PayloadPath, "Archiver le commit $Commit")) {
        & git archive --format=zip --output=$PayloadPath $Commit
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $PayloadPath -PathType Leaf)) { throw 'git archive a echoue.' }
    }
    $PayloadHash = (Get-FileHash -LiteralPath $PayloadPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $RequiredFiles = @(
        'INSTALLER-MARVIN.bat',
        'DESINSTALLER-MARVIN.bat',
        'start.bat',
        'package-lock.json',
        'backend/requirements.txt',
        'scripts/install-marvin-oneclick.ps1',
        'scripts/windows-install-components.json'
    )
    $Manifest = [ordered]@{
        schema_version = 1
        package_name = $PackageName
        product_version = $Version
        source_commit = $Commit
        created_at = (Get-Date).ToUniversalTime().ToString('o')
        payload = [ordered]@{
            file = 'payload.zip'
            sha256 = $PayloadHash
            format = 'git-archive-zip'
        }
        install_root = '%LOCALAPPDATA%\Programs\Marvin'
        personal_data_included = $false
        required_files = $RequiredFiles
        rollback = 'Le deploiement conserve une copie de code precedente lors d une mise a niveau; les donnees et runtime sont transferes atomiquement.'
    }
    [IO.File]::WriteAllText((Join-Path $PackageRoot 'package-manifest.json'), ($Manifest | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'package-installer-launcher.bat') -Destination (Join-Path $PackageRoot 'INSTALLER-MARVIN.bat')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install-marvin-package.ps1') -Destination (Join-Path $PackageRoot 'install-marvin-package.ps1')
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    $FinalZip = Join-Path $OutputDirectory "$PackageName.zip"
    Remove-Item -LiteralPath $FinalZip -Force -ErrorAction SilentlyContinue
    Compress-Archive -LiteralPath $PackageRoot -DestinationPath $FinalZip -CompressionLevel Optimal
    $FinalHash = (Get-FileHash -LiteralPath $FinalZip -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText("$FinalZip.sha256", "$FinalHash  $([IO.Path]::GetFileName($FinalZip))`n", [Text.UTF8Encoding]::new($false))
    [ordered]@{
        success = $true
        package = $FinalZip
        sha256 = $FinalHash
        payload_sha256 = $PayloadHash
        source_commit = $Commit
        product_version = $Version
        bytes = (Get-Item -LiteralPath $FinalZip).Length
    } | ConvertTo-Json -Depth 5
} finally {
    Pop-Location
    if ($BuildRoot -and (Test-Path -LiteralPath $BuildRoot)) { Remove-Item -LiteralPath $BuildRoot -Recurse -Force }
}
