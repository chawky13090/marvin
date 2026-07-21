[CmdletBinding()]
param(
    [string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $ProjectRoot 'data\install-capabilities.json'
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$DataRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot 'data'))
if (-not $OutputPath.StartsWith($DataRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Le rapport d installation doit rester dans le dossier data de Marvin.'
}

function Test-CommandAvailable {
    param([Parameter(Mandatory = $true)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function New-Capability {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][string]$Detail,
        [string]$Action = ''
    )
    [ordered]@{ status = $Status; detail = $Detail; action = $Action }
}

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
$IsAdmin = $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$Os = Get-CimInstance Win32_OperatingSystem
$Computer = Get-CimInstance Win32_ComputerSystem

$PythonPath = Join-Path $ProjectRoot 'backend\.venv\Scripts\python.exe'
$NodeModules = Join-Path $ProjectRoot 'node_modules'
$ElectronPath = Join-Path $ProjectRoot 'node_modules\electron\dist\electron.exe'
$Desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
$AvatarShortcut = Join-Path $Desktop 'Marvin Avatar.lnk'

$Core = [ordered]@{
    backend_venv = if (Test-Path -LiteralPath $PythonPath -PathType Leaf) {
        New-Capability 'available' 'Environnement Python isolé présent.'
    } else { New-Capability 'unavailable' 'Environnement Python absent.' 'Relancer INSTALLER-NOUVEAU-PC.bat.' }
    node_runtime = if (Test-CommandAvailable 'node') {
        New-Capability 'available' ((& node --version 2>$null) -join '')
    } else { New-Capability 'unavailable' 'Node.js absent.' 'Installer Node.js LTS puis relancer.' }
    node_dependencies = if (Test-Path -LiteralPath $NodeModules -PathType Container) {
        New-Capability 'available' 'Dépendances frontend présentes.'
    } else { New-Capability 'unavailable' 'node_modules absent.' 'Relancer INSTALLER-NOUVEAU-PC.bat.' }
    ollama = if ((Test-CommandAvailable 'ollama') -or (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'))) {
        New-Capability 'available' 'Runtime Ollama installé.'
    } else { New-Capability 'unavailable' 'Ollama absent.' 'Installer Ollama puis relancer.' }
}

$DockerCli = Test-CommandAvailable 'docker'
$DockerReady = $false
$DockerDetail = 'Docker CLI absent.'
if ($DockerCli) {
    $DockerVersion = (& docker version --format '{{.Server.Version}}' 2>$null)
    $DockerReady = $LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace(($DockerVersion -join ''))
    $DockerDetail = if ($DockerReady) { 'Docker Engine ' + (($DockerVersion -join '').Trim()) } else { 'Docker CLI présent, moteur indisponible.' }
}

$HyperVFeature = 'unknown'
$SandboxFeature = 'unknown'
$SandboxExecutable = Join-Path $env:SystemRoot 'System32\WindowsSandbox.exe'
try { $HyperVFeature = [string](Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -ErrorAction Stop).State } catch {}
try { $SandboxFeature = [string](Get-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -ErrorAction Stop).State } catch {}
$HyperVModule = $null -ne (Get-Module -ListAvailable -Name Hyper-V | Select-Object -First 1)
$DebianReady = $false
$WindowsReady = $false
if ($HyperVModule) {
    try {
        Import-Module Hyper-V -ErrorAction Stop
        $DebianReady = $null -ne (Get-VM -Name 'Marvin-Debian13-TestForge' -ErrorAction SilentlyContinue)
        $WindowsReady = $null -ne (Get-VM -Name 'Marvin-Windows11-TestForge' -ErrorAction SilentlyContinue)
    } catch {}
}

$Optional = [ordered]@{
    desktop_avatar = if ((Test-Path -LiteralPath $ElectronPath -PathType Leaf) -and (Test-Path -LiteralPath $AvatarShortcut -PathType Leaf)) {
        New-Capability 'available' 'Runtime Electron et raccourci Bureau présents.'
    } elseif (Test-Path -LiteralPath $ElectronPath -PathType Leaf) {
        New-Capability 'degraded' 'Runtime Electron présent, raccourci absent.' 'Exécuter scripts\install-desktop-avatar.ps1.'
    } else { New-Capability 'unavailable' 'Avatar optionnel absent.' 'Relancer l installateur; le socle reste utilisable.' }
    docker_test_forge = if ($DockerReady) { New-Capability 'available' $DockerDetail } elseif ($DockerCli) {
        New-Capability 'degraded' $DockerDetail 'Démarrer Docker Desktop.'
    } else { New-Capability 'unavailable' $DockerDetail 'Installer Docker Desktop pour Test Forge et SearXNG.' }
    hyperv = if ($HyperVModule) { New-Capability 'available' ('Module Hyper-V présent; état fonctionnalité : ' + $HyperVFeature) } elseif ($HyperVFeature -eq 'Disabled') {
        New-Capability 'unavailable' 'Hyper-V désactivé.' 'Activer uniquement sur une édition Windows compatible; redémarrage requis.'
    } else { New-Capability 'unavailable' ('État Hyper-V : ' + $HyperVFeature) 'Vérifier l édition Windows et les privilèges.' }
    windows_sandbox = if ($SandboxFeature -eq 'Enabled' -or (Test-Path -LiteralPath $SandboxExecutable -PathType Leaf)) { New-Capability 'available' 'Windows Sandbox installé.' } elseif ($SandboxFeature -eq 'Disabled') {
        New-Capability 'unavailable' 'Windows Sandbox désactivé.' 'Capacité facultative; activer sur Windows compatible si souhaité.'
    } else { New-Capability 'unavailable' ('État Sandbox : ' + $SandboxFeature) 'Capacité facultative.' }
    debian_native_vm = if ($DebianReady) { New-Capability 'available' 'VM Debian Test Forge détectée.' } else {
        New-Capability 'unavailable' 'VM Debian Test Forge absente.' 'Le socle et Docker restent utilisables; provisionner la VM pour les tests systemd natifs.'
    }
    windows_native_vm = if ($WindowsReady) { New-Capability 'available' 'VM Windows Test Forge détectée.' } else {
        New-Capability 'unavailable' 'VM Windows Test Forge absente.' 'Le socle reste utilisable; provisionner la VM pour la certification Windows native.'
    }
}

$CoreReady = @($Core.Values | Where-Object { $_.status -ne 'available' }).Count -eq 0
$Report = [ordered]@{
    schema_version = 1
    generated_at = [DateTime]::UtcNow.ToString('o')
    project_root = $ProjectRoot
    host = [ordered]@{
        computer_name = $env:COMPUTERNAME
        windows_caption = [string]$Os.Caption
        windows_version = [string]$Os.Version
        windows_build = [string]$Os.BuildNumber
        architecture = [string]$Os.OSArchitecture
        memory_bytes = [uint64]$Computer.TotalPhysicalMemory
        elevated = $IsAdmin
    }
    overall = if ($CoreReady) { 'available' } else { 'unavailable' }
    core = $Core
    optional = $Optional
}

$Directory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Path $Directory -Force | Out-Null
$Temporary = $OutputPath + '.tmp'
$Json = $Report | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($Temporary, $Json, [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $Temporary -Destination $OutputPath -Force
$Json
