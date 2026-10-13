[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-Sha256Hex([string]$Path) {
    $Stream = [System.IO.File]::OpenRead($Path)
    $Hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($Hasher.ComputeHash($Stream))).Replace('-', '').ToLowerInvariant()
    } finally {
        $Hasher.Dispose()
        $Stream.Dispose()
    }
}

$Archives = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter 'marvin-package.zip' -File)
if ($Archives.Count -ne 1) { throw 'Le paquet Marvin embarque est absent ou ambigu.' }
$Archive = $Archives[0].FullName
$Sidecar = "$Archive.sha256"
if (-not (Test-Path -LiteralPath $Sidecar -PathType Leaf)) { throw 'Empreinte du paquet embarque absente.' }
$Expected = ((Get-Content -LiteralPath $Sidecar -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
$Actual = Get-Sha256Hex -Path $Archive
if ($Expected -notmatch '^[0-9a-f]{64}$' -or $Actual -ne $Expected) { throw 'Integrite du paquet embarque invalide.' }

$Destination = Join-Path $env:TEMP ('marvin-private-installer-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Destination | Out-Null
try {
    Expand-Archive -LiteralPath $Archive -DestinationPath $Destination
    $Launcher = Get-ChildItem -LiteralPath $Destination -Filter 'INSTALLER-MARVIN.bat' -File -Recurse | Select-Object -First 1
    if ($null -eq $Launcher) { throw 'Lanceur Marvin absent du paquet extrait.' }
    $Process = Start-Process -FilePath $Launcher.FullName -WorkingDirectory $Launcher.DirectoryName -PassThru
    $Process.WaitForExit()
    exit $Process.ExitCode
} finally {
    if (Test-Path -LiteralPath $Destination) { Remove-Item -LiteralPath $Destination -Recurse -Force }
}
