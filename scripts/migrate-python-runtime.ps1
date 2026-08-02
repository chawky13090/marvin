[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [ValidateSet('Migrate', 'Rollback')]
    [string]$Action = 'Migrate',
    [string]$BackupPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$BackendRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot 'backend'))
$CurrentVenv = [IO.Path]::GetFullPath((Join-Path $BackendRoot '.venv'))
$Requirements = Join-Path $BackendRoot 'requirements.txt'
$Resolver = Join-Path $PSScriptRoot 'resolve-python-runtime.ps1'
$ArchitectureCheck = Join-Path $PSScriptRoot 'check_architecture.py'
$InstallState = Join-Path $ProjectRoot 'data\install\python-runtime.json'
$Timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'

function Assert-BackendChild {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Prefix)
    $Resolved = [IO.Path]::GetFullPath($Path)
    $ExpectedPrefix = $BackendRoot.TrimEnd('\') + '\' + $Prefix
    if (-not $Resolved.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Chemin refuse hors du perimetre backend attendu: $Resolved"
    }
    return $Resolved
}

function Assert-BackendStopped {
    if ($WhatIfPreference) { return }
    $Listener = Get-NetTCPConnection -LocalPort 8005 -State Listen -ErrorAction SilentlyContinue
    if ($Listener) {
        throw 'Le backend ecoute encore sur le port 8005. Arretez Marvin avant la migration ou le rollback.'
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$Label
    )
    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) { throw "$Label a echoue avec le code $LASTEXITCODE." }
    } finally {
        Pop-Location
    }
}

function Test-VenvRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$VenvPath,
        [bool]$RequirePortable = $true
    )
    $Python = Join-Path $VenvPath 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Python absent dans $VenvPath" }
    $RuntimeCheck = if ($RequirePortable) {
        "import json,python_runtime; r=python_runtime.inspect_runtime(); print(json.dumps(r)); raise SystemExit(0 if r['portable'] else 2)"
    } else {
        "import json,python_runtime,tools; r=python_runtime.inspect_runtime(); print(json.dumps(r))"
    }
    Invoke-Checked -FilePath $Python -Arguments @('-c', $RuntimeCheck) -WorkingDirectory $BackendRoot -Label 'Controle du runtime Python'
    Invoke-Checked -FilePath $Python -Arguments @('-m', 'pip', 'check') -WorkingDirectory $BackendRoot -Label 'pip check'
}

Assert-BackendStopped

if ($Action -eq 'Rollback') {
    if ([string]::IsNullOrWhiteSpace($BackupPath)) { throw 'BackupPath est obligatoire pour un rollback.' }
    $Backup = Assert-BackendChild -Path $BackupPath -Prefix '.venv.rollback-'
    if (-not (Test-Path -LiteralPath $Backup -PathType Container)) { throw "Sauvegarde introuvable: $Backup" }
    $Failed = Assert-BackendChild -Path (Join-Path $BackendRoot ('.venv.failed-' + $Timestamp)) -Prefix '.venv.failed-'
    if (-not $PSCmdlet.ShouldProcess($CurrentVenv, "Restaurer $Backup")) { return }
    if (Test-Path -LiteralPath $CurrentVenv) { Move-Item -LiteralPath $CurrentVenv -Destination $Failed }
    try {
        Move-Item -LiteralPath $Backup -Destination $CurrentVenv
        Test-VenvRuntime -VenvPath $CurrentVenv -RequirePortable $false
        Write-Output "Rollback termine. Runtime restaure: $CurrentVenv"
        if (Test-Path -LiteralPath $Failed) { Write-Output "Runtime remplace conserve pour diagnostic: $Failed" }
    } catch {
        if (Test-Path -LiteralPath $CurrentVenv) { Move-Item -LiteralPath $CurrentVenv -Destination ($CurrentVenv + '.rollback-failed-' + $Timestamp) }
        if (Test-Path -LiteralPath $Failed) { Move-Item -LiteralPath $Failed -Destination $CurrentVenv }
        throw
    }
    return
}

$RuntimeJson = & powershell -NoProfile -ExecutionPolicy Bypass -File $Resolver -Output Json
if ($LASTEXITCODE -ne 0) { throw 'Aucun runtime Python persistant compatible n a ete trouve.' }
$Runtime = ($RuntimeJson -join '') | ConvertFrom-Json
$BasePython = [IO.Path]::GetFullPath([string]$Runtime.path)
$Candidate = Assert-BackendChild -Path (Join-Path $BackendRoot ('.venv.next-' + $Timestamp)) -Prefix '.venv.next-'
$Backup = Assert-BackendChild -Path (Join-Path $BackendRoot ('.venv.rollback-' + $Timestamp)) -Prefix '.venv.rollback-'

if (-not $PSCmdlet.ShouldProcess($CurrentVenv, "Creer un environnement avec $BasePython et conserver $Backup")) { return }

try {
    Invoke-Checked -FilePath $BasePython -Arguments @('-m', 'venv', $Candidate) -WorkingDirectory $BackendRoot -Label 'Creation du venv candidat'
    $CandidatePython = Join-Path $Candidate 'Scripts\python.exe'
    Invoke-Checked -FilePath $CandidatePython -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip') -WorkingDirectory $BackendRoot -Label 'Mise a niveau de pip'
    Invoke-Checked -FilePath $CandidatePython -Arguments @('-m', 'pip', 'install', '-r', $Requirements) -WorkingDirectory $BackendRoot -Label 'Installation des dependances'
    Test-VenvRuntime -VenvPath $Candidate
    Invoke-Checked -FilePath $CandidatePython -Arguments @($ArchitectureCheck) -WorkingDirectory $ProjectRoot -Label 'Controle d architecture'

    if (Test-Path -LiteralPath $CurrentVenv) { Move-Item -LiteralPath $CurrentVenv -Destination $Backup }
    try {
        Move-Item -LiteralPath $Candidate -Destination $CurrentVenv
        Test-VenvRuntime -VenvPath $CurrentVenv
    } catch {
        $Rejected = Assert-BackendChild -Path (Join-Path $BackendRoot ('.venv.failed-' + $Timestamp)) -Prefix '.venv.failed-'
        if (Test-Path -LiteralPath $CurrentVenv) { Move-Item -LiteralPath $CurrentVenv -Destination $Rejected }
        if (Test-Path -LiteralPath $Backup) { Move-Item -LiteralPath $Backup -Destination $CurrentVenv }
        throw
    }

    $State = [ordered]@{
        schema_version = 1
        migrated_at = [DateTime]::UtcNow.ToString('o')
        selected_runtime = $Runtime
        active_venv = $CurrentVenv
        rollback_venv = $Backup
    }
    $StateDirectory = Split-Path -Parent $InstallState
    New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null
    $TemporaryState = $InstallState + '.tmp'
    [IO.File]::WriteAllText($TemporaryState, ($State | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $TemporaryState -Destination $InstallState -Force
    Write-Output "Migration terminee. Rollback conserve: $Backup"
} catch {
    if (Test-Path -LiteralPath $Candidate) {
        Write-Warning "Le candidat invalide est conserve pour diagnostic: $Candidate"
    }
    throw
}
