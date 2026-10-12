[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstallerPath = '',
    [switch]$AcceptLicense,
    [ValidateSet('auto', 'wsl-2', 'hyper-v')]
    [string]$Backend = 'auto',
    [ValidateRange(30, 900)]
    [int]$StartupTimeoutSeconds = 300,
    [switch]$Plan
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-HardwareVirtualization {
    $Processor = Get-CimInstance Win32_Processor | Select-Object -First 1
    if ($null -eq $Processor) { return $false }
    return [bool]$Processor.VirtualizationFirmwareEnabled -or [bool]$Processor.VMMonitorModeExtensions
}

function Resolve-DockerCli {
    $Command = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($Command) { return [string]$Command.Source }
    $Candidate = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
    if (Test-Path -LiteralPath $Candidate -PathType Leaf) { return $Candidate }
    return ''
}

function Test-DockerEngine([string]$DockerPath) {
    if ([string]::IsNullOrWhiteSpace($DockerPath)) { return $false }
    $Out = [IO.Path]::GetTempFileName()
    $Err = [IO.Path]::GetTempFileName()
    try {
        $Process = Start-Process -FilePath $DockerPath -ArgumentList @('info', '--format', '{{.ServerVersion}}') `
            -WindowStyle Hidden -PassThru -RedirectStandardOutput $Out -RedirectStandardError $Err
        if (-not $Process.WaitForExit(10000)) {
            & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
            return $false
        }
        $Process.WaitForExit()
        return [int]$Process.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace([IO.File]::ReadAllText($Out))
    } finally {
        Remove-Item -LiteralPath $Out, $Err -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-HardwareVirtualization)) {
    throw 'La virtualisation materielle VT-x/AMD-V est indisponible. Le profil Full ne peut pas garantir Docker.'
}

$DockerCli = Resolve-DockerCli
if (-not [string]::IsNullOrWhiteSpace($DockerCli) -and (Test-DockerEngine $DockerCli)) {
    Write-Output "Docker Engine deja disponible : $DockerCli"
    exit 0
}

if ([string]::IsNullOrWhiteSpace($DockerCli)) {
    if (-not $AcceptLicense) {
        throw 'Docker Desktop est absent. Son installation exige une acceptation explicite de la licence Docker.'
    }
    if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
        throw 'Installateur Docker Desktop verifie absent.'
    }
    $SelectedBackend = $Backend
    if ($SelectedBackend -eq 'auto') {
        # WSL 2 est le backend portable commun aux editions Windows prises en charge.
        # Le backend Hyper-V reste selectionnable explicitement sur Pro/Enterprise.
        $SelectedBackend = 'wsl-2'
    }
    if ($Plan) {
        Write-Output "Docker Desktop serait installe avec le backend $SelectedBackend."
        exit 0
    }
    if (-not $PSCmdlet.ShouldProcess('Docker Desktop', "Installer avec le backend $SelectedBackend")) { exit 2 }
    $TargetUser = [Environment]::UserName
    if ($TargetUser -notmatch '^[A-Za-z0-9._-]{1,64}$') { throw 'Nom utilisateur Windows non admissible pour Docker Desktop.' }
    $Arguments = @('install', '--quiet', '--accept-license', "--backend=$SelectedBackend", "--user=$TargetUser", '--always-run-service', '--no-windows-containers')
    $Process = Start-Process -FilePath $InstallerPath -ArgumentList $Arguments -Verb RunAs -Wait -PassThru
    if ([int]$Process.ExitCode -notin @(0, 3010)) { throw "Docker Desktop a retourne le code $($Process.ExitCode)." }
    if ([int]$Process.ExitCode -eq 3010) {
        throw 'Docker Desktop est installe mais Windows doit redemarrer avant la qualification du profil Full.'
    }
    $DockerCli = Resolve-DockerCli
    if ([string]::IsNullOrWhiteSpace($DockerCli)) { throw 'Docker CLI reste introuvable apres installation.' }
}

$Desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
if (Test-Path -LiteralPath $Desktop -PathType Leaf) {
    Start-Process -FilePath $Desktop -WindowStyle Hidden | Out-Null
}
$Deadline = [DateTimeOffset]::UtcNow.AddSeconds($StartupTimeoutSeconds)
do {
    if (Test-DockerEngine $DockerCli) { Write-Output "Docker Engine disponible : $DockerCli"; exit 0 }
    Start-Sleep -Seconds 3
} while ([DateTimeOffset]::UtcNow -lt $Deadline)
throw "Docker Desktop est installe mais son moteur ne repond pas apres $StartupTimeoutSeconds secondes."
