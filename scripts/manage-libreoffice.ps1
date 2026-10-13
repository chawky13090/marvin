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
if (-not $ResultPath.StartsWith($DataRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
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

function Get-PinnedOfficeInstaller($Component) {
    $Uri = [Uri]$Component.url
    if ($Uri.Scheme -ne 'https' -or $Uri.Host -notin @('downloadarchive.documentfoundation.org', 'download.visualstudio.microsoft.com')) {
        throw 'Origine du composant Office refusee.'
    }
    $Name = [string]$Component.file
    if ($Name -notmatch '^[A-Za-z0-9_.-]+\.(msi|exe)$' -or [string]$Component.sha256 -notmatch '^[a-f0-9]{64}$') {
        throw 'Identite du composant Office invalide.'
    }
    $Directory = Join-Path $ProjectRoot 'runtime\install\downloads'
    New-Item -ItemType Directory -Path $Directory -Force | Out-Null
    $Path = Join-Path $Directory $Name
    if ((Test-Path -LiteralPath $Path) -and (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -eq [string]$Component.sha256) { return $Path }
    $Temporary = $Path + '.' + [guid]::NewGuid().ToString('N') + '.partial'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $Uri -UseBasicParsing -OutFile $Temporary -TimeoutSec 300
        if ((Get-FileHash -LiteralPath $Temporary -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$Component.sha256) {
            throw 'SHA-256 du composant Office invalide; execution interdite.'
        }
        Move-Item -LiteralPath $Temporary -Destination $Path -Force
        return $Path
    } finally {
        if (Test-Path -LiteralPath $Temporary) { Remove-Item -LiteralPath $Temporary -Force }
    }
}

function Test-VcRuntime {
    $Runtime = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64' -ErrorAction SilentlyContinue
    if (-not $Runtime -or $Runtime.Installed -ne 1) { return $false }
    $Version = [version](([string]$Runtime.Version).TrimStart('v'))
    return $Version -ge [version]$Manifest.vc_runtime.version
}

function Invoke-PinnedOfficeInstaller([string]$Path, $Component, [switch]$Msi) {
    # Conserver un verrou lecture sans partage ecriture/suppression entre hash et lancement.
    $Stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $Hasher = [Security.Cryptography.SHA256]::Create()
    $Process = $null
    try {
        $Hash = ([BitConverter]::ToString($Hasher.ComputeHash($Stream))).Replace('-', '').ToLowerInvariant()
        if ($Hash -ne [string]$Component.sha256) { throw 'Composant Office modifie avant execution.' }
        if ($Msi) {
            $Executable = Join-Path $env:SystemRoot 'System32\msiexec.exe'
            $Arguments = @('/i', ('"{0}"' -f $Path), '/qn', '/norestart')
        } else {
            $Signature = Get-AuthenticodeSignature -LiteralPath $Path
            if ($Signature.Status -ne 'Valid' -or -not $Signature.SignerCertificate -or
                $Signature.SignerCertificate.Subject.IndexOf([string]$Component.publisher, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
                throw 'Signature du prerequis VC++ invalide.'
            }
            $Executable = $Path
            $Arguments = @('/install', '/quiet', '/norestart')
        }
        $Principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
        $Parameters = @{ FilePath=$Executable; ArgumentList=$Arguments; PassThru=$true }
        if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { $Parameters.Verb='RunAs' }
        $Process = Start-Process @Parameters
        $null = $Process.Handle
        Wait-LibreOfficeOperation $Process
        $ExitCode = [int]$Process.ExitCode
        if ($ExitCode -notin @(0,3010)) { throw "Installation Office refusee, code $ExitCode; aucune relance automatique." }
        return $ExitCode
    } finally {
        if ($Process) { $Process.Dispose() }
        $Hasher.Dispose()
        $Stream.Dispose()
    }
}

function Invoke-DirectOfficeRemoval([string]$ProductCode) {
    if ($ProductCode -notmatch '^\{[A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12}\}$') { throw 'ProductCode Office invalide.' }
    $Parameters = @{ FilePath=(Join-Path $env:SystemRoot 'System32\msiexec.exe'); ArgumentList=@('/x',$ProductCode,'/qn','/norestart'); PassThru=$true }
    $Principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { $Parameters.Verb='RunAs' }
    $Process = Start-Process @Parameters
    try {
        $null=$Process.Handle
        Wait-LibreOfficeOperation $Process
        $Code=[int]$Process.ExitCode
        if ($Code -notin @(0,1605,3010)) { throw "Desinstallation Office non confirmee, code $Code." }
        return $Code
    } finally { $Process.Dispose() }
}

if ($Action -eq 'Ensure') {
    $Before = Get-LibreOfficeStatus
    if (-not $Before.verified) {
        $Winget = Get-Command winget.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $Winget) {
            if ($PSCmdlet.ShouldProcess(([string]$Manifest.package_id), 'Installer LibreOffice et VC++ sans WinGet')) {
                if (-not (Test-VcRuntime)) {
                    $VcPath = Get-PinnedOfficeInstaller $Manifest.vc_runtime
                    $VcExit = Invoke-PinnedOfficeInstaller $VcPath $Manifest.vc_runtime
                    if ($VcExit -eq 3010) {
                        $Before.error = 'Redemarrage requis par VC++; Office reprendra apres redemarrage.'
                        $Before.reboot_required = $true
                        Save-Result $Before
                        exit 3010
                    }
                    if (-not (Test-VcRuntime)) { throw 'Prerequis VC++ non confirme apres installation.' }
                }
                $MsiPath = Get-PinnedOfficeInstaller $Manifest.direct_msi
                $MsiExit = Invoke-PinnedOfficeInstaller $MsiPath $Manifest.direct_msi -Msi
                if ($MsiExit -eq 3010) {
                    $After = Get-LibreOfficeStatus
                    $After.reboot_required = $true
                    Save-Result $After
                    exit 3010
                }
            }
        } elseif ($PSCmdlet.ShouldProcess(([string]$Manifest.package_id), "Installer LibreOffice $($Manifest.version)")) {
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
        $Winget = Get-Command winget.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $Winget) {
            $RemovalCode=Invoke-DirectOfficeRemoval ([string]$Manifest.direct_msi.product_code)
            if ($RemovalCode -eq 3010) { $Status=Get-LibreOfficeStatus; $Status.reboot_required=$true; Save-Result $Status; exit 3010 }
        } else {
            $Process = Start-Process -FilePath $Winget.Source -ArgumentList @(
                'uninstall', '--id', [string]$Manifest.package_id, '--exact', '--silent',
                '--disable-interactivity', '--accept-source-agreements'
            ) -PassThru -Verb RunAs
            try {
                $null=$Process.Handle
                Wait-LibreOfficeOperation $Process
                if ($Process.ExitCode -ne 0) { throw "Desinstallation WinGet echouee : $($Process.ExitCode)." }
            } finally { $Process.Dispose() }
        }
    }
}

$Status = Get-LibreOfficeStatus
Save-Result $Status
if ($Action -eq 'Verify' -and -not $Status.verified) { exit 3 }
if ($Action -eq 'Uninstall' -and $Status.verified) { throw 'LibreOffice reste present apres desinstallation; aucune relance automatique.' }
