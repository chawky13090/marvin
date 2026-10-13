[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet('Status', 'Ensure', 'Verify', 'Uninstall')]
    [string]$Action = 'Status',
    [string]$ResultPath = '',
    [ValidateRange(30, 3600)]
    [int]$OperationTimeoutSeconds = 900
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$ManifestPath = Join-Path $PSScriptRoot 'libreoffice-component.json'
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($ResultPath)) {
    $ResultPath = Join-Path $ProjectRoot 'data\libreoffice-capability.json'
}
$ResultPath = [IO.Path]::GetFullPath($ResultPath)
$DataRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot 'data'))
if (-not $ResultPath.StartsWith($DataRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Le rapport LibreOffice doit rester dans le dossier data de Marvin.'
}

function Find-Soffice {
    $Candidates = @(
        (Join-Path $env:ProgramFiles 'LibreOffice\program\soffice.com'),
        $(if (${env:ProgramFiles(x86)}) { Join-Path ${env:ProgramFiles(x86)} 'LibreOffice\program\soffice.com' }),
        $(if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'Programs\LibreOffice\program\soffice.com' })
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
    $Command = Get-Command soffice.com -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($Command) { return [string]$Command.Source }
    return [string]($Candidates | Select-Object -First 1)
}

function Get-LibreOfficeStatus {
    $Path = Find-Soffice
    $Version = ''
    $Verified = $false
    $ErrorMessage = ''
    if ($Path) {
        try {
            $VersionOutput = & $Path --headless --version 2>&1
            $Verified = $LASTEXITCODE -eq 0
            $Version = (($VersionOutput | Select-Object -First 1) -as [string]).Trim()
        } catch { $ErrorMessage = $_.Exception.Message }
    }
    [ordered]@{
        schema_version = 1
        generated_at = [DateTime]::UtcNow.ToString('o')
        status = $(if ($Verified) { 'available' } elseif ($Path) { 'degraded' } else { 'unavailable' })
        executable = $Path
        version = $Version
        pinned_version = [string]$Manifest.version
        verified = $Verified
        error = $ErrorMessage
    }
}

function Save-Result($Value) {
    $Directory = Split-Path -Parent $ResultPath
    New-Item -ItemType Directory -Path $Directory -Force | Out-Null
    $Temporary = $ResultPath + '.tmp'
    [IO.File]::WriteAllText($Temporary, ($Value | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $Temporary -Destination $ResultPath -Force
    $Value
}

function Wait-LibreOfficeOperation($Process) {
    if (-not $Process.WaitForExit($OperationTimeoutSeconds * 1000)) {
        & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
        throw "Operation LibreOffice non confirmee apres $OperationTimeoutSeconds secondes; verifier l inventaire avant une nouvelle tentative."
    }
    $Process.WaitForExit()
}

if ($Action -eq 'Ensure') {
    $Before = Get-LibreOfficeStatus
    if (-not $Before.verified) {
        $Winget = Get-Command winget.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $Winget) {
            $Before.error = 'WinGet absent : installation automatique indisponible sur cet hôte.'
            Save-Result $Before
            exit 2
        }
        if ($PSCmdlet.ShouldProcess(([string]$Manifest.package_id), "Installer LibreOffice $($Manifest.version)")) {
            $LogDir = Join-Path $ProjectRoot 'runtime\logs'
            New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
            $Arguments = @(
                'install', '--id', [string]$Manifest.package_id, '--exact',
                '--version', [string]$Manifest.version, '--source', 'winget', '--silent',
                '--disable-interactivity', '--accept-source-agreements', '--accept-package-agreements'
            )
            # Les dépendances VC++ et le MSI LibreOffice sont des composants
            # système. Demander l'UAC ici évite une attente invisible dans un
            # désinstalleur enfant lancé depuis un compte standard.
            $Process = Start-Process -FilePath $Winget.Source -ArgumentList $Arguments -Verb RunAs -PassThru
            Wait-LibreOfficeOperation $Process
            if ($Process.ExitCode -notin @(0, -1978335189)) {
                throw "WinGet a échoué avec le code $($Process.ExitCode)."
            }
        }
    }
    $After = Get-LibreOfficeStatus
    Save-Result $After
    if (-not $After.verified) { exit 3 }
    exit 0
}

if ($Action -eq 'Uninstall') {
    if ($PSCmdlet.ShouldProcess(([string]$Manifest.package_id), 'Désinstaller LibreOffice')) {
        $Winget = Get-Command winget.exe -ErrorAction Stop | Select-Object -First 1
        $Process = Start-Process -FilePath $Winget.Source -ArgumentList @(
            'uninstall', '--id', [string]$Manifest.package_id, '--exact', '--silent',
            '--disable-interactivity', '--accept-source-agreements'
        ) -PassThru -WindowStyle Hidden
        Wait-LibreOfficeOperation $Process
        if ($Process.ExitCode -ne 0) { throw "Désinstallation WinGet échouée : $($Process.ExitCode)." }
    }
}

$Status = Get-LibreOfficeStatus
Save-Result $Status
if ($Action -eq 'Verify' -and -not $Status.verified) { exit 3 }
