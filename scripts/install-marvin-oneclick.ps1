[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Plan,
    [switch]$NoStart,
    [switch]$SkipModels,
    [switch]$SkipOptional,
    [ValidateSet('Full', 'Core')]
    [string]$DeploymentProfile = 'Full',
    [switch]$AcceptDockerDesktopLicense,
    [switch]$TestLogging
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$DryRunRequested = [bool]$WhatIfPreference
$WhatIfPreference = $false
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$RuntimeRoot = Join-Path $ProjectRoot 'runtime\install'
$ManagedRoot = Join-Path $ProjectRoot 'runtime\managed'
$DownloadRoot = Join-Path $RuntimeRoot 'downloads'
$StatePath = Join-Path $RuntimeRoot 'state.json'
$LogPath = Join-Path $RuntimeRoot 'install.log.jsonl'
$EnvironmentPath = Join-Path $RuntimeRoot 'environment.bat'
$ComponentsPath = Join-Path $PSScriptRoot 'windows-install-components.json'
$Components = Get-Content -LiteralPath $ComponentsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$StartedAt = Get-Date
$InstallId = [guid]::NewGuid().ToString('N')
$StageResults = [ordered]@{}
$DownloadedEvidence = [System.Collections.Generic.List[object]]::new()
$InstallLogMaxBytes = 2MB
$InstallLogMaxArchives = 5
$script:CurrentStage = ''
$script:DockerLicenseAccepted = [bool]$AcceptDockerDesktopLicense
if ($DryRunRequested) { $Plan = $true }

function Register-InstallResumeAfterRestart {
    $Arguments = [System.Collections.Generic.List[string]]::new()
    $Arguments.Add('-NoProfile')
    $Arguments.Add('-ExecutionPolicy')
    $Arguments.Add('Bypass')
    $Arguments.Add('-File')
    $Arguments.Add(('"{0}"' -f $PSCommandPath))
    $Arguments.Add('-DeploymentProfile')
    $Arguments.Add($DeploymentProfile)
    if ($NoStart) { $Arguments.Add('-NoStart') }
    if ($SkipModels) { $Arguments.Add('-SkipModels') }
    if ($SkipOptional) { $Arguments.Add('-SkipOptional') }
    if ($script:DockerLicenseAccepted) { $Arguments.Add('-AcceptDockerDesktopLicense') }
    $Command = 'powershell.exe ' + ($Arguments -join ' ')
    $RunOnce = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce'
    New-Item -Path $RunOnce -Force | Out-Null
    Set-ItemProperty -Path $RunOnce -Name 'MarvinInstallerResume' -Value $Command -Type String
    Save-State -Status 'restart_required' -CurrentStage $script:CurrentStage -ErrorMessage ''
    Write-InstallEvent -Stage $script:CurrentStage -Result 'degraded' -Message 'Redemarrage Windows requis; reprise enregistree pour la prochaine ouverture de session.'
}

function Rotate-InstallLog {
    if (-not (Test-Path -LiteralPath $LogPath -PathType Leaf)) { return }
    if ((Get-Item -LiteralPath $LogPath).Length -lt $InstallLogMaxBytes) { return }
    $Oldest = "$LogPath.$InstallLogMaxArchives"
    Remove-Item -LiteralPath $Oldest -Force -ErrorAction SilentlyContinue
    for ($Index = $InstallLogMaxArchives - 1; $Index -ge 1; $Index--) {
        $Source = "$LogPath.$Index"
        if (Test-Path -LiteralPath $Source -PathType Leaf) {
            Move-Item -LiteralPath $Source -Destination "$LogPath.$($Index + 1)" -Force
        }
    }
    Move-Item -LiteralPath $LogPath -Destination "$LogPath.1" -Force
}

function Write-InstallEvent {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][string]$Result,
        [Parameter(Mandatory = $true)][string]$Message,
        [hashtable]$Context = @{}
    )
    if ($Plan) { return }
    try {
        New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
        Rotate-InstallLog
        $Event = [ordered]@{
            schema_version = 1
            timestamp = (Get-Date).ToUniversalTime().ToString('o')
            severity_text = if ($Result -eq 'failed') { 'ERROR' } elseif ($Result -eq 'degraded') { 'WARNING' } else { 'INFO' }
            event_name = 'marvin.install.stage'
            component = 'marvin-windows-installer'
            trace_id = $InstallId
            stage = $Stage
            outcome = if ($Result -eq 'succeeded') { 'success' } elseif ($Result -eq 'failed') { 'failure' } else { $Result }
            message = $Message
            attributes = $Context
        }
        $Line = ($Event | ConvertTo-Json -Compress -Depth 8) + [Environment]::NewLine
        [IO.File]::AppendAllText($LogPath, $Line, [Text.UTF8Encoding]::new($false))
    } catch {
        Write-Warning "Journal installateur indisponible : $($_.Exception.Message)"
    }
}

function Write-AtomicJson {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)]$Value)
    $Parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $Parent -Force | Out-Null
    $Temporary = "$Path.$PID.tmp"
    [IO.File]::WriteAllText($Temporary, ($Value | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $Temporary -Destination $Path -Force
}

function Save-State {
    param([string]$Status, [string]$CurrentStage = '', [string]$ErrorMessage = '')
    if ($Plan) { return }
    $State = [ordered]@{
        schema_version = 1
        install_id = $InstallId
        installer_version = '1.0'
        deployment_profile = $DeploymentProfile
        project_root = $ProjectRoot
        status = $Status
        current_stage = $CurrentStage
        started_at = $StartedAt.ToUniversalTime().ToString('o')
        updated_at = (Get-Date).ToUniversalTime().ToString('o')
        error = $ErrorMessage
        stages = $StageResults
        downloads = @($DownloadedEvidence)
    }
    Write-AtomicJson -Path $StatePath -Value $State
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = $ProjectRoot,
        [int[]]$SuccessExitCodes = @(0)
    )
    $Process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory -Wait -PassThru -NoNewWindow
    if ($SuccessExitCodes -notcontains [int]$Process.ExitCode) {
        throw "$FilePath a retourne le code $($Process.ExitCode)."
    }
    return [int]$Process.ExitCode
}

function Get-VerifiedDownload {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Sha256,
        [string]$AuthenticodeSubjectContains = ''
    )
    New-Item -ItemType Directory -Path $DownloadRoot -Force | Out-Null
    $Destination = Join-Path $DownloadRoot $Name
    $Expected = $Sha256.ToLowerInvariant()
    $ValidExisting = $false
    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        $Observed = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
        $ValidExisting = $Observed -eq $Expected
        if (-not $ValidExisting) { Remove-Item -LiteralPath $Destination -Force }
    }
    if (-not $ValidExisting) {
        $Temporary = "$Destination.part"
        Remove-Item -LiteralPath $Temporary -Force -ErrorAction SilentlyContinue
        $LastError = $null
        for ($Attempt = 1; $Attempt -le 3; $Attempt++) {
            try {
                Invoke-WebRequest -Uri $Url -OutFile $Temporary -UseBasicParsing -TimeoutSec 1800
                $Observed = (Get-FileHash -LiteralPath $Temporary -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($Observed -ne $Expected) { throw "SHA-256 invalide pour $Name." }
                Move-Item -LiteralPath $Temporary -Destination $Destination -Force
                $LastError = $null
                break
            } catch {
                $LastError = $_
                Remove-Item -LiteralPath $Temporary -Force -ErrorAction SilentlyContinue
                if ($Attempt -lt 3) { Start-Sleep -Seconds ([math]::Pow(2, $Attempt)) }
            }
        }
        if ($null -ne $LastError) { throw $LastError }
    }
    $ObservedHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ObservedHash -ne $Expected) { throw "Le cache de telechargement $Name ne correspond pas au manifeste." }
    if (-not [string]::IsNullOrWhiteSpace($AuthenticodeSubjectContains)) {
        $Signature = Get-AuthenticodeSignature -FilePath $Destination
        if ($Signature.Status -ne 'Valid' -or $null -eq $Signature.SignerCertificate) {
            throw "La signature Authenticode de $Name n'est pas valide."
        }
        if ($Signature.SignerCertificate.Subject.IndexOf($AuthenticodeSubjectContains, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
            throw "L'editeur Authenticode de $Name ne correspond pas au manifeste."
        }
    }
    $DownloadedEvidence.Add([ordered]@{ name = $Name; url = $Url; sha256 = $ObservedHash })
    return $Destination
}

function Expand-VerifiedArchive {
    param([Parameter(Mandatory = $true)][string]$Archive, [Parameter(Mandatory = $true)][string]$Destination)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $DestinationFull = [IO.Path]::GetFullPath($Destination)
    $Zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($Entry in $Zip.Entries) {
            if ([string]::IsNullOrWhiteSpace($Entry.FullName)) { continue }
            $Candidate = [IO.Path]::GetFullPath((Join-Path $DestinationFull $Entry.FullName))
            if (-not $Candidate.StartsWith($DestinationFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Archive refusee : chemin sortant $($Entry.FullName)."
            }
        }
    } finally {
        $Zip.Dispose()
    }
    Remove-Item -LiteralPath $Destination -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -Force
}

function Install-ManagedArchive {
    param(
        [Parameter(Mandatory = $true)][string]$Archive,
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$ExecutableName
    )
    $Staging = "$Target.next-$InstallId"
    Expand-VerifiedArchive -Archive $Archive -Destination $Staging
    $Executable = Get-ChildItem -LiteralPath $Staging -Filter $ExecutableName -File -Recurse | Select-Object -First 1
    if ($null -eq $Executable) { throw "$ExecutableName est absent de l'archive." }
    $PayloadRoot = $Executable.Directory.FullName
    $Backup = "$Target.rollback-$(Get-Date -Format 'yyyyMMddHHmmss')"
    if (Test-Path -LiteralPath $Target) { Move-Item -LiteralPath $Target -Destination $Backup }
    try {
        New-Item -ItemType Directory -Path $Target -Force | Out-Null
        Get-ChildItem -LiteralPath $PayloadRoot -Force | ForEach-Object {
            Move-Item -LiteralPath $_.FullName -Destination $Target -Force
        }
        Remove-Item -LiteralPath $Staging -Recurse -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path -LiteralPath (Join-Path $Target $ExecutableName) -PathType Leaf)) {
            throw "$ExecutableName n'est pas exploitable apres installation."
        }
        Remove-Item -LiteralPath $Backup -Recurse -Force -ErrorAction SilentlyContinue
    } catch {
        Remove-Item -LiteralPath $Target -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $Backup) { Move-Item -LiteralPath $Backup -Destination $Target }
        throw
    }
}

function Resolve-Python {
    $PreviousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'SilentlyContinue'
        $Output = @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'resolve-python-runtime.ps1') -Output Path 2>$null)
        $ExitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $PreviousPreference }
    if ($ExitCode -eq 0 -and $Output.Count -gt 0) { return [string]$Output[-1] }
    return ''
}

function Resolve-Node {
    $PreviousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'SilentlyContinue'
        $Output = @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'resolve-node-runtime.ps1') -Output Path 2>$null)
        $ExitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $PreviousPreference }
    if ($ExitCode -eq 0 -and $Output.Count -gt 0) { return [string]$Output[-1] }
    return ''
}

function Resolve-Ollama {
    $PreviousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'SilentlyContinue'
        $Output = @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'resolve-ollama-exe.ps1') 2>$null)
        $ExitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $PreviousPreference }
    if ($ExitCode -eq 0 -and $Output.Count -gt 0) { return [string]$Output[-1] }
    return ''
}

function Invoke-InstallStage {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [switch]$Optional
    )
    $script:CurrentStage = $Name
    Write-Host "[$Name]" -ForegroundColor Cyan
    if ($Plan) {
        $StageResults[$Name] = [ordered]@{ status = 'planned'; duration_ms = 0 }
        Write-Host '  PLANIFIE (aucune modification)' -ForegroundColor DarkCyan
        return
    }
    Save-State -Status 'running' -CurrentStage $Name
    $StageStart = Get-Date
    try {
        & $Action
        $Duration = [math]::Round(((Get-Date) - $StageStart).TotalMilliseconds)
        $StageResults[$Name] = [ordered]@{ status = 'succeeded'; duration_ms = $Duration }
        Write-InstallEvent -Stage $Name -Result 'succeeded' -Message 'Etape terminee.' -Context @{ duration_ms = $Duration }
        Write-Host "  OK ($Duration ms)" -ForegroundColor Green
    } catch {
        $Duration = [math]::Round(((Get-Date) - $StageStart).TotalMilliseconds)
        $Status = if ($Optional) { 'degraded' } else { 'failed' }
        $StageResults[$Name] = [ordered]@{ status = $Status; duration_ms = $Duration; error = $_.Exception.Message }
        Write-InstallEvent -Stage $Name -Result $Status -Message $_.Exception.Message -Context @{ duration_ms = $Duration }
        if ($Optional) {
            Write-Warning "Capacite optionnelle degradee : $($_.Exception.Message)"
        } else {
            Save-State -Status 'failed' -CurrentStage $Name -ErrorMessage $_.Exception.Message
            throw
        }
    }
    Save-State -Status 'running' -CurrentStage $Name
}

function Stop-MarvinIfRunning {
    $Listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in @(3000, 8005) })
    if ($Listeners.Count -eq 0) { return }
    $StopScript = Join-Path $PSScriptRoot 'stop-marvin.ps1'
    if (-not (Test-Path -LiteralPath $StopScript)) { throw 'Marvin tourne mais son arret controle est indisponible.' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StopScript -AllowActiveWorkInterruption
    if ($LASTEXITCODE -ne 0) { throw 'Marvin n a pas pu etre arrete proprement avant installation.' }
}

function Get-MinimumFreeBytesForCurrentRun {
    $FreshMinimum = [uint64]$Components.minimum_free_bytes
    $ResumeMinimum = [uint64]$Components.resume_minimum_free_bytes
    $ManagedMarkers = @(
        (Join-Path $ManagedRoot 'python\python.exe'),
        (Join-Path $ManagedRoot 'node\node.exe'),
        (Join-Path $ManagedRoot 'ollama\ollama.exe')
    )
    $InstalledManagedRuntimeCount = @($ManagedMarkers | Where-Object {
        Test-Path -LiteralPath $_ -PathType Leaf
    }).Count
    if ($InstalledManagedRuntimeCount -gt 0) {
        # Une reprise ne doit pas exiger de nouveau l'espace déjà consommé par
        # les runtimes vérifiés. Les étapes suivantes revalident chaque
        # composant; ce seuil ne contourne donc aucun contrôle d'intégrité.
        return $ResumeMinimum
    }
    return $FreshMinimum
}

function Write-ManagedEnvironment {
    param([Parameter(Mandatory = $true)][string]$NodePath, [Parameter(Mandatory = $true)][string]$OllamaPath)
    $NodeDir = Split-Path -Parent $NodePath
    $OllamaDir = Split-Path -Parent $OllamaPath
    $ModelRoot = Join-Path $ProjectRoot 'data\models\ollama'
    New-Item -ItemType Directory -Path $ModelRoot -Force | Out-Null
    $Lines = @(
        '@echo off',
        ('set "PATH={0};{1};%PATH%"' -f $NodeDir, $OllamaDir),
        ('set "MARVIN_MANAGED_NODE={0}"' -f $NodePath),
        ('set "MARVIN_MANAGED_OLLAMA={0}"' -f $OllamaPath),
        ('set "OLLAMA_MODELS={0}"' -f $ModelRoot)
    )
    [IO.File]::WriteAllLines($EnvironmentPath, $Lines, [Text.UTF8Encoding]::new($false))
    $env:PATH = "$NodeDir;$OllamaDir;$env:PATH"
    $env:OLLAMA_MODELS = $ModelRoot
}

function New-DesktopShortcuts {
    $Desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
    $Shell = New-Object -ComObject WScript.Shell
    $LaunchShortcut = $Shell.CreateShortcut((Join-Path $Desktop 'Marvin.lnk'))
    $LaunchShortcut.TargetPath = Join-Path $ProjectRoot 'start.bat'
    $LaunchShortcut.WorkingDirectory = $ProjectRoot
    $LaunchShortcut.Description = 'Demarrer Marvin'
    $LaunchShortcut.Save()
    $Uninstall = Join-Path $ProjectRoot 'DESINSTALLER-MARVIN.bat'
    if (Test-Path -LiteralPath $Uninstall -PathType Leaf) {
        $UninstallShortcut = $Shell.CreateShortcut((Join-Path $Desktop 'Desinstaller Marvin.lnk'))
        $UninstallShortcut.TargetPath = $Uninstall
        $UninstallShortcut.WorkingDirectory = $ProjectRoot
        $UninstallShortcut.Description = 'Desinstaller Marvin proprement'
        $UninstallShortcut.Save()
    }
}

if ($TestLogging) {
    Write-InstallEvent -Stage 'self_test' -Result 'succeeded' -Message 'Rotation installer testee.' -Context @{ duration_ms = 0 }
    exit 0
}

$MutexName = 'Local\MarvinInstaller-' + ([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($ProjectRoot))).Replace('=', '').Replace('/', '_').Replace('+', '-').Substring(0, [math]::Min(48, ([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($ProjectRoot))).Length))
$Mutex = [Threading.Mutex]::new($false, $MutexName)
if (-not $Mutex.WaitOne(0)) { throw 'Une installation Marvin est deja en cours pour ce dossier.' }

try {
    Write-Host ''
    Write-Host 'Marvin - Installation Windows en un clic' -ForegroundColor Cyan
    Write-Host "Cible : $ProjectRoot"
    if ($Plan) { Write-Host 'Mode PLAN : aucune modification ne sera appliquee.' -ForegroundColor Yellow }
    Write-Host ''

    Invoke-InstallStage -Name 'preflight' -Action {
        if ($env:OS -ne 'Windows_NT') { throw 'Cet installateur cible uniquement Windows.' }
        if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows 64 bits est requis.' }
        $Os = Get-CimInstance Win32_OperatingSystem
        if ([int]$Os.BuildNumber -lt [int]$Components.minimum_windows_build) {
            throw "Build Windows $($Os.BuildNumber) non supporte; minimum $($Components.minimum_windows_build)."
        }
        $Drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($ProjectRoot).Substring(0, 1))
        $RequiredFreeBytes = Get-MinimumFreeBytesForCurrentRun
        if ([uint64]$Drive.Free -lt $RequiredFreeBytes) {
            $RequiredGiB = [math]::Ceiling($RequiredFreeBytes / 1GB)
            throw "Au moins $RequiredGiB Gio libres sont requis pour cette installation ou reprise et son rollback."
        }
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'package-lock.json'))) { throw 'package-lock.json absent.' }
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'backend\requirements.txt'))) { throw 'requirements.txt absent.' }
    }

    if (-not $Plan) { Stop-MarvinIfRunning }

    $PythonPath = ''
    Invoke-InstallStage -Name 'python_runtime' -Action {
        $script:PythonPath = Resolve-Python
        if ([string]::IsNullOrWhiteSpace($script:PythonPath)) {
            $PythonComponent = $Components.python
            $Installer = Get-VerifiedDownload -Name "python-$($PythonComponent.version)-amd64.exe" `
                -Url ([string]$PythonComponent.url) -Sha256 ([string]$PythonComponent.sha256) `
                -AuthenticodeSubjectContains ([string]$PythonComponent.authenticode_subject_contains)
            $PythonHome = Join-Path $ManagedRoot 'python'
            New-Item -ItemType Directory -Path $ManagedRoot -Force | Out-Null
            $Arguments = @(
                '/quiet', 'InstallAllUsers=0', "TargetDir=`"$PythonHome`"", 'PrependPath=0',
                'Include_launcher=0', 'Include_test=0', 'Include_doc=0', 'Include_debug=0',
                'Include_symbols=0', 'Include_pip=1', 'Include_tcltk=1', 'Include_dev=1',
                'Include_exe=1', 'Shortcuts=0', 'AssociateFiles=0'
            )
            Invoke-External -FilePath $Installer -ArgumentList $Arguments -SuccessExitCodes @(0, 3010) | Out-Null
            $script:PythonPath = Join-Path $PythonHome 'python.exe'
        }
        if (-not (Test-Path -LiteralPath $script:PythonPath -PathType Leaf)) { throw 'Python compatible introuvable apres installation.' }
        & $script:PythonPath -m pip --version *> $null
        if ($LASTEXITCODE -ne 0) { Invoke-External -FilePath $script:PythonPath -ArgumentList @('-m', 'ensurepip', '--upgrade') | Out-Null }
    }

    $NodePath = ''
    Invoke-InstallStage -Name 'node_runtime' -Action {
        $script:NodePath = Resolve-Node
        if ([string]::IsNullOrWhiteSpace($script:NodePath)) {
            $NodeComponent = $Components.node
            $Archive = Get-VerifiedDownload -Name "node-v$($NodeComponent.version)-win-x64.zip" `
                -Url ([string]$NodeComponent.url) -Sha256 ([string]$NodeComponent.sha256)
            Install-ManagedArchive -Archive $Archive -Target (Join-Path $ManagedRoot 'node') -ExecutableName 'node.exe'
            $script:NodePath = Join-Path $ManagedRoot 'node\node.exe'
        }
        if (-not (Test-Path -LiteralPath $script:NodePath -PathType Leaf)) { throw 'Node.js compatible introuvable apres installation.' }
        $NodeDir = Split-Path -Parent $script:NodePath
        $env:PATH = "$NodeDir;$env:PATH"
        Invoke-External -FilePath $script:NodePath -ArgumentList @('-e', "require('assert').strictEqual(process.arch,'x64')") | Out-Null
    }

    $OllamaPath = ''
    Invoke-InstallStage -Name 'ollama_runtime' -Action {
        $script:OllamaPath = Resolve-Ollama
        if ([string]::IsNullOrWhiteSpace($script:OllamaPath)) {
            $OllamaComponent = $Components.ollama
            $Archive = Get-VerifiedDownload -Name "ollama-$($OllamaComponent.version)-windows-amd64.zip" `
                -Url ([string]$OllamaComponent.url) -Sha256 ([string]$OllamaComponent.sha256)
            Install-ManagedArchive -Archive $Archive -Target (Join-Path $ManagedRoot 'ollama') -ExecutableName 'ollama.exe'
            $script:OllamaPath = Join-Path $ManagedRoot 'ollama\ollama.exe'
        }
        if (-not (Test-Path -LiteralPath $script:OllamaPath -PathType Leaf)) { throw 'Ollama introuvable apres installation.' }
        Write-ManagedEnvironment -NodePath $script:NodePath -OllamaPath $script:OllamaPath
        Invoke-External -FilePath $script:OllamaPath -ArgumentList @('--version') | Out-Null
    }

    Invoke-InstallStage -Name 'backend_dependencies' -Action {
        $Venv = Join-Path $ProjectRoot 'backend\.venv'
        $Rollback = "$Venv.rollback-$(Get-Date -Format 'yyyyMMddHHmmss')"
        if (Test-Path -LiteralPath $Venv) { Move-Item -LiteralPath $Venv -Destination $Rollback }
        try {
            Invoke-External -FilePath $script:PythonPath -ArgumentList @('-m', 'venv', $Venv) | Out-Null
            $VenvPython = Join-Path $Venv 'Scripts\python.exe'
            Invoke-External -FilePath $VenvPython -ArgumentList @('-m', 'pip', 'install', '--no-cache-dir', '--upgrade', 'pip') | Out-Null
            Invoke-External -FilePath $VenvPython -ArgumentList @('-m', 'pip', 'install', '--no-cache-dir', '-r', (Join-Path $ProjectRoot 'backend\requirements.txt')) | Out-Null
            Invoke-External -FilePath $VenvPython -ArgumentList @('-m', 'pip', 'check') | Out-Null
            $PyWin32 = Join-Path $Venv 'Scripts\pywin32_postinstall.py'
            if (Test-Path -LiteralPath $PyWin32) { Invoke-External -FilePath $VenvPython -ArgumentList @($PyWin32, '-install') | Out-Null }
            Push-Location (Join-Path $ProjectRoot 'backend')
            try { & $VenvPython -c "import main,tools; print(len(tools.TOOLS_SPEC))" | Out-Null; if ($LASTEXITCODE -ne 0) { throw 'Import backend invalide.' } } finally { Pop-Location }
            Remove-Item -LiteralPath $Rollback -Recurse -Force -ErrorAction SilentlyContinue
        } catch {
            Remove-Item -LiteralPath $Venv -Recurse -Force -ErrorAction SilentlyContinue
            if (Test-Path -LiteralPath $Rollback) { Move-Item -LiteralPath $Rollback -Destination $Venv }
            throw
        }
    }

    Invoke-InstallStage -Name 'frontend_dependencies' -Action {
        $NodeModules = Join-Path $ProjectRoot 'node_modules'
        $Rollback = "$NodeModules.rollback-$(Get-Date -Format 'yyyyMMddHHmmss')"
        if (Test-Path -LiteralPath $NodeModules) { Move-Item -LiteralPath $NodeModules -Destination $Rollback }
        try {
            $NodeDir = Split-Path -Parent $script:NodePath
            $Npm = Join-Path $NodeDir 'npm.cmd'
            if (-not (Test-Path -LiteralPath $Npm)) { $Npm = (Get-Command npm.cmd -ErrorAction Stop).Source }
            $env:npm_config_cache = Join-Path $DownloadRoot 'npm-cache'
            Invoke-External -FilePath $Npm -ArgumentList @('ci', '--no-audit', '--no-fund') | Out-Null
            Invoke-External -FilePath $script:NodePath -ArgumentList @('-e', "require('sharp'); require('next/package.json')") | Out-Null
            Remove-Item -LiteralPath $Rollback -Recurse -Force -ErrorAction SilentlyContinue
        } catch {
            Remove-Item -LiteralPath $NodeModules -Recurse -Force -ErrorAction SilentlyContinue
            if (Test-Path -LiteralPath $Rollback) { Move-Item -LiteralPath $Rollback -Destination $NodeModules }
            throw
        }
    }

    Invoke-InstallStage -Name 'data_and_configuration' -Action {
        New-Item -ItemType Directory -Path (Join-Path $ProjectRoot 'data') -Force | Out-Null
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'manage-data-acl.ps1') -Action Apply -NoConfirm
        if ($LASTEXITCODE -ne 0) { throw 'Durcissement ACL du dossier data refuse.' }
        $EnvironmentExample = Join-Path $ProjectRoot '.env.local.example'
        $EnvironmentLocal = Join-Path $ProjectRoot '.env.local'
        if (-not (Test-Path -LiteralPath $EnvironmentLocal) -and (Test-Path -LiteralPath $EnvironmentExample)) {
            Copy-Item -LiteralPath $EnvironmentExample -Destination $EnvironmentLocal
        }
    }

    if ($DeploymentProfile -eq 'Full') {
        Invoke-InstallStage -Name 'docker_and_searxng_required' -Action {
            # Le PATH du processus courant peut dater d'avant l'installation
            # Docker. Le helper résout aussi le chemin canonique Program Files
            # et constitue donc l'unique source de vérité.
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'ensure-docker-desktop.ps1')
            $DockerEnsureExitCode = $LASTEXITCODE
            if ($DockerEnsureExitCode -eq 3010) {
                Register-InstallResumeAfterRestart
                Write-Host 'Windows doit redemarrer. Marvin reprendra automatiquement a la prochaine ouverture de session.' -ForegroundColor Yellow
                exit 3010
            }
            $DockerReady = $DockerEnsureExitCode -eq 0
            if (-not $DockerReady) {
                $DockerComponent = $Components.docker_desktop
                $Answer = ''
                $DockerInstaller = Get-VerifiedDownload -Name "docker-desktop-$($DockerComponent.version)-amd64.exe" `
                    -Url ([string]$DockerComponent.url) -Sha256 ([string]$DockerComponent.sha256) `
                    -AuthenticodeSubjectContains ([string]$DockerComponent.authenticode_subject_contains)
                if (-not $AcceptDockerDesktopLicense -and -not $Plan) {
                    $Answer = Read-Host 'Docker Desktop est requis par le profil Full. Tapez ACCEPTER pour accepter sa licence et continuer'
                    if ($Answer -cne 'ACCEPTER') { throw 'Licence Docker Desktop non acceptee; profil Full interrompu.' }
                    $script:DockerLicenseAccepted = $true
                }
                $DockerArguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'ensure-docker-desktop.ps1'), '-InstallerPath', $DockerInstaller)
                if ($AcceptDockerDesktopLicense -or $Answer -ceq 'ACCEPTER') { $DockerArguments += '-AcceptLicense' }
                & powershell.exe @DockerArguments
                if ($LASTEXITCODE -eq 3010) {
                    Register-InstallResumeAfterRestart
                    Write-Host 'Windows doit redemarrer. Marvin reprendra automatiquement a la prochaine ouverture de session.' -ForegroundColor Yellow
                    exit 3010
                }
                if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop requis ne peut pas etre qualifie.' }
            }
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot 'docker\searxng\start-searxng.ps1')
            if ($LASTEXITCODE -ne 0) { throw 'SearXNG requis ne peut pas etre qualifie.' }
        }
    } else {
        $StageResults['docker_and_searxng_required'] = [ordered]@{ status = 'skipped'; reason = 'Profil Core explicitement choisi' }
    }

    if (-not $SkipModels) {
        Invoke-InstallStage -Name 'local_models_and_context' -Optional -Action {
            $PortOutput = @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'resolve-ollama-port.ps1'))
            if ($LASTEXITCODE -ne 0 -or $PortOutput.Count -eq 0) { throw 'Aucun port Ollama local disponible.' }
            $OllamaPort = [int]$PortOutput[-1]
            $env:OLLAMA_HOST = "127.0.0.1:$OllamaPort"
            $env:OLLAMA_URL = "http://127.0.0.1:$OllamaPort"
            $Ready = $false
            try { Invoke-RestMethod -Uri "$($env:OLLAMA_URL)/api/version" -TimeoutSec 2 | Out-Null; $Ready = $true } catch {}
            if (-not $Ready) {
                Start-Process -FilePath $script:OllamaPath -ArgumentList @('serve') -WindowStyle Hidden | Out-Null
                for ($Attempt = 0; $Attempt -lt 120 -and -not $Ready; $Attempt++) {
                    Start-Sleep -Milliseconds 500
                    try { Invoke-RestMethod -Uri "$($env:OLLAMA_URL)/api/version" -TimeoutSec 2 | Out-Null; $Ready = $true } catch {}
                }
            }
            if (-not $Ready) { throw 'Ollama ne repond pas apres 60 secondes.' }
            $VenvPython = Join-Path $ProjectRoot 'backend\.venv\Scripts\python.exe'
            $PlanFile = Join-Path $RuntimeRoot 'local-model-plan.txt'
            & $VenvPython (Join-Path $PSScriptRoot 'plan_local_models.py') | Set-Content -LiteralPath $PlanFile -Encoding UTF8
            if ($LASTEXITCODE -ne 0) { throw 'Plan local de modeles indisponible.' }
            $Models = @(Get-Content -LiteralPath $PlanFile | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
            if ($Models -notcontains 'nomic-embed-text') { $Models += 'nomic-embed-text' }
            foreach ($Model in $Models) {
                if ($Model -notmatch '^[A-Za-z0-9._:/-]+$') { throw "Nom de modele refuse : $Model" }
                Invoke-External -FilePath $script:OllamaPath -ArgumentList @('pull', $Model) | Out-Null
            }
            & $VenvPython (Join-Path $PSScriptRoot 'qualify-local-models.py') --repetitions 3
            if ($LASTEXITCODE -ne 0) { throw 'Aucun modele agent local qualifie.' }
            & $VenvPython (Join-Path $PSScriptRoot 'calibrate-ollama-context.py') --verify --repetitions 5 --output (Join-Path $ProjectRoot 'data\install\ollama-context-profile.json')
            if ($LASTEXITCODE -ne 0) { throw 'Calibration locale non certifiee; repli 8192/f16 conserve.' }
        }
    } else {
        $StageResults['local_models_and_context'] = [ordered]@{ status = 'skipped'; reason = 'SkipModels explicite' }
    }

    if (-not $SkipOptional) {
        Invoke-InstallStage -Name 'libreoffice_optional' -Optional -Action {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'manage-libreoffice.ps1') -Action Ensure
            if ($LASTEXITCODE -ne 0) { throw 'LibreOffice indisponible; validation documentaire structurelle maintenue.' }
        }
    } else {
        $StageResults['libreoffice_optional'] = [ordered]@{ status = 'skipped'; reason = 'SkipOptional explicite' }
    }

    Invoke-InstallStage -Name 'production_build' -Action {
        $NodeDir = Split-Path -Parent $script:NodePath
        $Npm = Join-Path $NodeDir 'npm.cmd'
        if (-not (Test-Path -LiteralPath $Npm)) { $Npm = (Get-Command npm.cmd -ErrorAction Stop).Source }
        Invoke-External -FilePath $Npm -ArgumentList @('run', 'build') | Out-Null
    }

    Invoke-InstallStage -Name 'shortcuts_and_report' -Action {
        New-DesktopShortcuts
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'write-install-report.ps1') | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Rapport de capacites non genere.' }
    }

    if (-not $NoStart) {
        Invoke-InstallStage -Name 'runtime_validation' -Action {
            $StartBatch = Join-Path $ProjectRoot 'start.bat'
            Start-Process -FilePath $env:ComSpec -ArgumentList @('/d', '/c', 'call', "`"$StartBatch`"") -WorkingDirectory $ProjectRoot -WindowStyle Minimized | Out-Null
            $BackendReady = $false
            $FrontendReady = $false
            $Deadline = (Get-Date).AddMinutes(4)
            do {
                try {
                    $Health = Invoke-RestMethod -Uri 'http://127.0.0.1:8005/api/health' -TimeoutSec 4
                    $BackendReady = $Health.status -eq 'ok' -and [int]$Health.tools_count -eq 364
                } catch {}
                try {
                    $Frontend = Invoke-WebRequest -Uri 'http://127.0.0.1:3000' -UseBasicParsing -TimeoutSec 4
                    $FrontendReady = $Frontend.StatusCode -eq 200
                } catch {}
                if (-not ($BackendReady -and $FrontendReady)) { Start-Sleep -Seconds 2 }
            } while ((Get-Date) -lt $Deadline -and -not ($BackendReady -and $FrontendReady))
            if (-not $BackendReady) { throw 'Backend non pret apres installation.' }
            if (-not $FrontendReady) { throw 'Frontend non pret apres installation.' }
            Start-Process 'http://127.0.0.1:3000'
        }
    } else {
        $StageResults['runtime_validation'] = [ordered]@{ status = 'skipped'; reason = 'NoStart explicite' }
    }

    if ($Plan) {
        [ordered]@{ schema_version = 1; mode = 'plan'; stages = @($StageResults.Keys) } | ConvertTo-Json -Depth 5
        exit 0
    }
    if (Test-Path -LiteralPath $DownloadRoot) {
        Remove-Item -LiteralPath $DownloadRoot -Recurse -Force
    }
    Save-State -Status 'completed'
    Write-InstallEvent -Stage 'installation' -Result 'succeeded' -Message 'Installation Marvin terminee.' -Context @{ duration_ms = [math]::Round(((Get-Date) - $StartedAt).TotalMilliseconds) }
    Write-Host ''
    Write-Host 'INSTALLATION TERMINEE - Marvin est pret.' -ForegroundColor Green
    Write-Host "Rapport : $StatePath"
    Write-Host 'Interface : http://127.0.0.1:3000'
    Write-Host ''
    exit 0
} catch {
    Write-InstallEvent -Stage 'installation' -Result 'failed' -Message $_.Exception.Message
    Save-State -Status 'failed' -CurrentStage $script:CurrentStage -ErrorMessage $_.Exception.Message
    Write-Error $_
    exit 1
} finally {
    try { $Mutex.ReleaseMutex() } catch {}
    $Mutex.Dispose()
}
