[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [string]$VMName = 'Marvin-Windows11-TestForge',
    [string]$CheckpointName = 'Marvin-Clean',
    [switch]$IncludeModels,
    [switch]$IncludeOptional,
    [switch]$Confirmed
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$PackagePath = [IO.Path]::GetFullPath($PackagePath)
$SecretPath = Join-Path $env:TEMP ('.marvin-vm-secret-' + [guid]::NewGuid().ToString('N') + '.txt')
$Session = $null
$MonitorSession = $null
$InstallJob = $null
$MonitorJob = $null
$Result = [ordered]@{
    schema_version = 1
    package = [IO.Path]::GetFileName($PackagePath)
    vm_name = $VMName
    checkpoint_name = $CheckpointName
    success = $false
    checkpoint_restored_before = $false
    checkpoint_restored_after = $false
    error = $null
    guest = $null
}

if (-not $Confirmed) { throw 'La qualification installe réellement le paquet dans la VM; utilisez -Confirmed.' }
if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) { throw 'Paquet Marvin absent.' }
$Sidecar = $PackagePath + '.sha256'
if (-not (Test-Path -LiteralPath $Sidecar -PathType Leaf)) { throw 'Sidecar SHA-256 externe absent.' }
$Expected = ((Get-Content -LiteralPath $Sidecar -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
$Observed = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Expected -notmatch '^[0-9a-f]{64}$' -or $Observed -ne $Expected) { throw 'SHA-256 externe du paquet invalide.' }

try {
    $HostDrive = Get-PSDrive -Name ([IO.Path]::GetPathRoot((Get-VMHardDiskDrive -VMName $VMName | Select-Object -First 1).Path).Substring(0, 1))
    if ([uint64]$HostDrive.Free -lt 40GB) { throw 'Moins de 40 Gio libres sur le volume hôte de la VM; qualification refusée.' }
    $Checkpoint = Get-VMCheckpoint -VMName $VMName -Name $CheckpointName -ErrorAction Stop
    if ($null -eq $Checkpoint) { throw 'Checkpoint de référence absent.' }

    $Python = Join-Path $ProjectRoot 'backend\.venv\Scripts\python.exe'
    & $Python (Join-Path $PSScriptRoot 'materialize-vm-secret.py') --key vm_lab.windows11.guest_password --output $SecretPath | Out-Null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $SecretPath -PathType Leaf)) { throw 'Secret invité indisponible.' }
    & icacls.exe $SecretPath /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
    $Password = Get-Content -LiteralPath $SecretPath -Raw
    $Credential = [PSCredential]::new('marvin', (ConvertTo-SecureString $Password -AsPlainText -Force))
    $Password = $null

    $VM = Get-VM -Name $VMName -ErrorAction Stop
    if ($VM.State -ne 'Off') { Stop-VM -VM $VM -TurnOff -Force }
    Restore-VMCheckpoint -VMName $VMName -Name $CheckpointName -Confirm:$false
    $Result.checkpoint_restored_before = $true
    Start-VM -Name $VMName | Out-Null

    $Deadline = (Get-Date).AddMinutes(4)
    do {
        try { $Session = New-PSSession -VMName $VMName -Credential $Credential -ErrorAction Stop }
        catch { Start-Sleep -Seconds 3 }
    } until ($Session -or (Get-Date) -gt $Deadline)
    if (-not $Session) { throw 'PowerShell Direct indisponible après quatre minutes.' }
    $MonitorSession = New-PSSession -VMName $VMName -Credential $Credential -ErrorAction Stop

    $GuestPreflight = Invoke-Command -Session $Session -ScriptBlock {
        $Drive = Get-PSDrive C
        [ordered]@{
            os = (Get-CimInstance Win32_OperatingSystem).Caption
            build = [Environment]::OSVersion.Version.Build
            free_bytes = [uint64]$Drive.Free
            user = [Environment]::UserName
            is_admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        }
    }
    if ([uint64]$GuestPreflight.free_bytes -lt 40GB) { throw 'Moins de 40 Gio libres dans la VM invitée.' }

    $GuestRoot = 'C:\Marvin\InstallerQualification'
    Invoke-Command -Session $Session -ScriptBlock {
        param($Path)
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    } -ArgumentList $GuestRoot
    Copy-Item -LiteralPath $PackagePath -Destination (Join-Path $GuestRoot 'Marvin.zip') -ToSession $Session -Force

    $SkipModels = -not $IncludeModels
    $SkipOptional = -not $IncludeOptional
    $InstallJob = Invoke-Command -Session $Session -AsJob -ScriptBlock {
        param($Root, $SkipModelsRequested, $SkipOptionalRequested, $Preflight)
        $ErrorActionPreference = 'Stop'
        Expand-Archive -LiteralPath (Join-Path $Root 'Marvin.zip') -DestinationPath $Root -Force
        $Package = Get-ChildItem -LiteralPath $Root -Directory | Where-Object Name -Like 'Marvin-Windows-v*' | Select-Object -First 1
        if ($null -eq $Package) { throw 'Racine du paquet extraite introuvable.' }
        $Installer = Join-Path $Package.FullName 'install-marvin-package.ps1'
        $Stdout = Join-Path $Root 'install.stdout.txt'
        $Stderr = Join-Path $Root 'install.stderr.txt'
        # PowerShell Direct n'a pas de bureau interactif fiable. L'installation
        # est donc terminée sans ouvrir le navigateur, puis le qualifier lance
        # lui-même start.bat et prouve les deux services HTTP sous une borne
        # distincte. Le parcours utilisateur interactif reste inchangé.
        $Arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $Installer), '-NoStart')
        if ($SkipModelsRequested) { $Arguments += '-SkipModels' }
        if ($SkipOptionalRequested) { $Arguments += '-SkipOptional' }
        $Process = Start-Process -FilePath 'powershell.exe' -ArgumentList $Arguments -WorkingDirectory $Package.FullName -PassThru -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
        $Finished = $Process.WaitForExit(5400000)
        if (-not $Finished) {
            & taskkill.exe /PID $Process.Id /T /F | Out-Null
            throw 'Installation invitée expirée après 90 minutes.'
        }
        $Process.Refresh()
        $ExitCode = [int]$Process.ExitCode
        $Target = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\Marvin'
        $StatePath = Join-Path $Target 'runtime\install\state.json'
        $State = if (Test-Path -LiteralPath $StatePath) { Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json } else { $null }
        $InstallLog = Join-Path $Target 'runtime\install\install.log.jsonl'
        $Health = $null
        $Frontend = $null
        $StartExitCode = $null
        $StartStdoutText = ''
        $StartStderrText = ''
        if ($ExitCode -eq 0) {
            $StartBatch = Join-Path $Target 'start.bat'
            if (-not (Test-Path -LiteralPath $StartBatch -PathType Leaf)) { throw 'Lanceur installé introuvable.' }
            $StartStdout = Join-Path $Root 'start.stdout.txt'
            $StartStderr = Join-Path $Root 'start.stderr.txt'
            $StartProcess = Start-Process -FilePath $env:ComSpec `
                -ArgumentList @('/d', '/c', 'call', ('"{0}"' -f $StartBatch)) `
                -WorkingDirectory $env:SystemRoot -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput $StartStdout -RedirectStandardError $StartStderr
            $StartTimedOut = -not $StartProcess.WaitForExit(300000)
            if ($StartTimedOut) {
                & taskkill.exe /PID $StartProcess.Id /T /F | Out-Null
                $StartExitCode = 124
            } else {
                $StartProcess.Refresh()
                $StartExitCode = [int]$StartProcess.ExitCode
            }
            $StartStdoutText = if (Test-Path -LiteralPath $StartStdout) { [string](Get-Content -LiteralPath $StartStdout -Raw) } else { '' }
            $StartStderrText = if (Test-Path -LiteralPath $StartStderr) { [string](Get-Content -LiteralPath $StartStderr -Raw) } else { '' }
            if ($StartStdoutText.Length -gt 12000) { $StartStdoutText = $StartStdoutText.Substring($StartStdoutText.Length - 12000) }
            if ($StartStderrText.Length -gt 12000) { $StartStderrText = $StartStderrText.Substring($StartStderrText.Length - 12000) }
            $RuntimeDeadline = (Get-Date).AddMinutes(4)
            do {
                try { $Health = Invoke-RestMethod -Uri 'http://127.0.0.1:8005/api/health' -TimeoutSec 4 } catch { $Health = $null }
                try { $Frontend = (Invoke-WebRequest -Uri 'http://127.0.0.1:3000' -UseBasicParsing -TimeoutSec 4).StatusCode } catch { $Frontend = $null }
                if (-not ($Health -and $Health.status -eq 'ok' -and [int]$Health.tools_count -eq 364 -and $Frontend -eq 200)) {
                    Start-Sleep -Seconds 2
                }
            } while ((Get-Date) -lt $RuntimeDeadline -and -not ($Health -and $Health.status -eq 'ok' -and [int]$Health.tools_count -eq 364 -and $Frontend -eq 200))
        }
        $StdoutText = if (Test-Path -LiteralPath $Stdout) { [string](Get-Content -LiteralPath $Stdout -Raw) } else { '' }
        $StderrText = if (Test-Path -LiteralPath $Stderr) { [string](Get-Content -LiteralPath $Stderr -Raw) } else { '' }
        if ($StdoutText.Length -gt 12000) { $StdoutText = $StdoutText.Substring($StdoutText.Length - 12000) }
        if ($StderrText.Length -gt 12000) { $StderrText = $StderrText.Substring($StderrText.Length - 12000) }
        [ordered]@{
            preflight = $Preflight
            exit_code = $ExitCode
            state_status = if ($State) { [string]$State.status } else { $null }
            failed_stage = if ($State -and $State.status -ne 'completed') { [string]$State.current_stage } else { $null }
            state_error = if ($State -and $State.status -ne 'completed') { [string]$State.error } else { $null }
            installer_log_tail = if (Test-Path -LiteralPath $InstallLog) { [string]((Get-Content -LiteralPath $InstallLog -Tail 3) -join "`n") } else { $null }
            health_status = if ($Health) { [string]$Health.status } else { $null }
            health_version = if ($Health) { [string]$Health.version } else { $null }
            tools_count = if ($Health) { [int]$Health.tools_count } else { $null }
            frontend_status = $Frontend
            start_exit_code = $StartExitCode
            start_stdout_tail = $StartStdoutText
            start_stderr_tail = $StartStderrText
            stdout_tail = $StdoutText
            stderr_tail = $StderrText
        }
    } -ArgumentList $GuestRoot, $SkipModels, $SkipOptional, $GuestPreflight

    $InstallDeadline = (Get-Date).AddMinutes(90)
    $LastStage = ''
    do {
        Start-Sleep -Seconds 30
        $JobState = [string]$InstallJob.State
        if ([uint64](Get-PSDrive -Name $HostDrive.Name).Free -lt 5GB) {
            Stop-Job -Job $InstallJob -ErrorAction SilentlyContinue
            throw 'Moins de 5 Gio libres sur le volume hôte pendant la qualification; campagne interrompue avant saturation.'
        }
        try {
            $MonitorJob = Invoke-Command -Session $MonitorSession -AsJob -ScriptBlock {
                $Target = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\Marvin'
                $StatePath = Join-Path $Target 'runtime\install\state.json'
                if (Test-Path -LiteralPath $StatePath) {
                    $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
                    [ordered]@{ status = [string]$State.status; stage = [string]$State.current_stage; free_bytes = [uint64](Get-PSDrive C).Free }
                } else {
                    [ordered]@{ status = 'bootstrap'; stage = 'package_publish'; free_bytes = [uint64](Get-PSDrive C).Free }
                }
            }
            if (-not (Wait-Job -Job $MonitorJob -Timeout 10)) {
                Stop-Job -Job $MonitorJob -ErrorAction SilentlyContinue
                throw 'Sonde PowerShell Direct expirée après 10 secondes.'
            }
            $Progress = Receive-Job -Job $MonitorJob -ErrorAction Stop
            if ([string]$Progress.stage -ne $LastStage) {
                $LastStage = [string]$Progress.stage
                Write-Host ("VM install stage: {0} ({1} Gio libres dans l'invité)" -f $LastStage, [math]::Round(([uint64]$Progress.free_bytes / 1GB), 1))
            }
        } catch {
            Write-Warning "Sonde de progression VM indisponible : $($_.Exception.Message)"
        } finally {
            if ($MonitorJob) {
                if ($MonitorJob.State -in @('Running', 'NotStarted')) { Stop-Job -Job $MonitorJob -ErrorAction SilentlyContinue }
                Remove-Job -Job $MonitorJob -ErrorAction SilentlyContinue
                $MonitorJob = $null
            }
        }
    } while ($JobState -in @('Running', 'NotStarted') -and (Get-Date) -lt $InstallDeadline)

    if ((Get-Date) -ge $InstallDeadline -and $InstallJob.State -in @('Running', 'NotStarted')) {
        Stop-Job -Job $InstallJob -ErrorAction SilentlyContinue
        throw 'Installation invitée expirée après 90 minutes.'
    }
    if ($InstallJob.State -eq 'Failed') {
        $Reason = [string]$InstallJob.ChildJobs[0].JobStateInfo.Reason
        throw "Commande de qualification invitée échouée : $Reason"
    }
    $GuestResult = Receive-Job -Job $InstallJob -ErrorAction Stop

    $Result.guest = $GuestResult
    $Result.success = [bool](
        $GuestResult.exit_code -eq 0 -and
        $GuestResult.state_status -eq 'completed' -and
        $GuestResult.health_status -eq 'ok' -and
        $GuestResult.health_version -eq '2.654.0' -and
        $GuestResult.tools_count -eq 364 -and
        $GuestResult.frontend_status -eq 200 -and
        $GuestResult.start_exit_code -eq 0
    )
} catch {
    $Result.error = $_.Exception.Message
} finally {
    if ($MonitorJob) {
        if ($MonitorJob.State -in @('Running', 'NotStarted')) { Stop-Job -Job $MonitorJob -ErrorAction SilentlyContinue }
        Remove-Job -Job $MonitorJob -ErrorAction SilentlyContinue
    }
    if ($InstallJob) {
        if ($InstallJob.State -in @('Running', 'NotStarted')) { Stop-Job -Job $InstallJob -ErrorAction SilentlyContinue }
        Remove-Job -Job $InstallJob -ErrorAction SilentlyContinue
    }
    if ($MonitorSession) { Remove-PSSession $MonitorSession -ErrorAction SilentlyContinue }
    if ($Session) { Remove-PSSession $Session -ErrorAction SilentlyContinue }
    $VM = Get-VM -Name $VMName -ErrorAction SilentlyContinue
    if ($VM -and $VM.State -ne 'Off') { Stop-VM -VM $VM -TurnOff -Force -ErrorAction SilentlyContinue }
    if ($VM) {
        try {
            Restore-VMCheckpoint -VMName $VMName -Name $CheckpointName -Confirm:$false -ErrorAction Stop
            $Result.checkpoint_restored_after = $true
        } catch { $Result.checkpoint_restored_after = $false }
    }
    Remove-Item -LiteralPath $SecretPath -Force -ErrorAction SilentlyContinue
}

$Result | ConvertTo-Json -Depth 10
if (-not $Result.success) { exit 1 }
