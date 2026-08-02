[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [ValidateSet('Install', 'Uninstall', 'Status')]
    [string]$Action = 'Status',
    [ValidateRange(443, 65535)]
    [int]$Port = 443,
    [switch]$Allow8443Fallback
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ServiceName = 'MarvinHttpsGateway'
$ServiceAccount = 'NT AUTHORITY\LocalService'
$FirewallRuleName = 'Marvin HTTPS Gateway (Private)'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'marvin-https-logging.ps1')
$Runtime = Join-Path $Root 'runtime\https'
$Caddy = Join-Path $Runtime 'caddy.exe'
$Config = Join-Path $Runtime 'caddy.json'
$StatePath = Join-Path $Runtime 'service-state.json'

function Test-IsAdministrator {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
    return $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-PortListener([int]$CandidatePort) {
    return @(Get-NetTCPConnection -LocalPort $CandidatePort -State Listen -ErrorAction SilentlyContinue)
}

function Get-ServiceSnapshot {
    $Service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    $Listeners = @(Get-PortListener -CandidatePort $Port)
    return [pscustomobject]@{
        service_name = $ServiceName
        installed = $null -ne $Service
        status = if ($null -ne $Service) { [string]$Service.Status } else { 'Absent' }
        start_type = if ($null -ne $Service) { [string]$Service.StartType } else { $null }
        requested_port = $Port
        listening = $Listeners.Count -gt 0
        listener_pids = @($Listeners | Select-Object -ExpandProperty OwningProcess -Unique)
        firewall_rule = $null -ne (Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue)
    }
}

if ($Action -eq 'Status') {
    Get-ServiceSnapshot
    exit 0
}

if (-not (Test-IsAdministrator)) {
    throw "L'action $Action exige une console PowerShell exécutée en administrateur."
}

if ($Action -eq 'Uninstall') {
    if ($PSCmdlet.ShouldProcess($ServiceName, 'Arrêter et supprimer le service HTTPS Marvin')) {
        $Existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($null -ne $Existing) {
            if ($Existing.Status -ne 'Stopped') {
                Stop-Service -Name $ServiceName -Force
                $Existing.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(20))
            }
            & sc.exe delete $ServiceName | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Échec de suppression du service $ServiceName ($LASTEXITCODE)."
            }
        }
        Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue |
            Remove-NetFirewallRule
        Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
        Write-MarvinHttpsEvent -Action 'service-uninstall' -Result 'success' -Context @{
            service_name = $ServiceName
        }
    }
    Get-ServiceSnapshot
    exit 0
}

if (-not (Test-Path -LiteralPath $Caddy -PathType Leaf)) {
    throw 'Caddy absent. Exécutez install-marvin-https.ps1 avant de créer le service.'
}

$SelectedPort = $Port
$Listeners = @(Get-PortListener -CandidatePort $SelectedPort)
if ($Listeners.Count -gt 0) {
    $ExistingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    $ServicePid = $null
    if ($null -ne $ExistingService) {
        $ServiceProcess = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -ErrorAction SilentlyContinue
        if ($null -ne $ServiceProcess) { $ServicePid = [int]$ServiceProcess.ProcessId }
    }
    $ForeignListeners = @($Listeners | Where-Object { $_.OwningProcess -ne $ServicePid })
    if ($ForeignListeners.Count -gt 0) {
        if ($Allow8443Fallback -and $SelectedPort -ne 8443 -and @(Get-PortListener 8443).Count -eq 0) {
            $SelectedPort = 8443
        } else {
            $Owners = ($ForeignListeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
            throw "Le port $SelectedPort est déjà utilisé par le(s) PID $Owners. Aucun remplacement implicite."
        }
    }
}

if (-not $PSCmdlet.ShouldProcess(
        "$ServiceName sur TCP/$SelectedPort",
        "Installer le service sous $ServiceAccount et la règle pare-feu Domain,Private"
    )) {
    exit 0
}

$PreviousConfig = if (Test-Path -LiteralPath $Config) { Get-Content -Raw -LiteralPath $Config } else { $null }
$PreviousState = if (Test-Path -LiteralPath (Join-Path $Runtime 'state.json')) {
    Get-Content -Raw -LiteralPath (Join-Path $Runtime 'state.json')
} else { $null }
$ExistingManagedService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
$AdminListeners = @(Get-NetTCPConnection -LocalPort 2019 -State Listen -ErrorAction SilentlyContinue)
$UnmanagedGatewayWasRunning = $null -eq $ExistingManagedService -and $AdminListeners.Count -gt 0

try {
    if ($UnmanagedGatewayWasRunning -and (Test-Path -LiteralPath $Config -PathType Leaf)) {
        & $Caddy stop --config $Config | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Impossible d'arrêter la passerelle HTTPS interactive ($LASTEXITCODE)." }
    }
    & (Join-Path $PSScriptRoot 'write-marvin-https-config.ps1') -Port $SelectedPort | Out-Null
    & $Caddy validate --config $Config | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Configuration Caddy invalide ($LASTEXITCODE)." }

    # SID S-1-5-19 = LocalService; le SID évite les problèmes de langue Windows.
    & icacls.exe $Runtime /grant '*S-1-5-19:(OI)(CI)M' /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Impossible d'accorder l'accès borné au runtime HTTPS ($LASTEXITCODE)." }

    $Existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    $BinaryPath = '"{0}" run --config "{1}"' -f $Caddy, $Config
    if ($null -eq $Existing) {
        & sc.exe create $ServiceName binPath= $BinaryPath start= auto obj= $ServiceAccount | Out-Null
    } else {
        if ($Existing.Status -ne 'Stopped') {
            Stop-Service -Name $ServiceName -Force
            $Existing.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(20))
        }
        & sc.exe config $ServiceName binPath= $BinaryPath start= auto obj= $ServiceAccount | Out-Null
    }
    if ($LASTEXITCODE -ne 0) { throw "Échec de configuration du service $ServiceName ($LASTEXITCODE)." }
    & sc.exe description $ServiceName 'Passerelle HTTPS locale de Marvin (Caddy)' | Out-Null

    Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $FirewallRuleName -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort $SelectedPort -Profile Domain,Private -Program $Caddy | Out-Null

    Start-Service -Name $ServiceName
    (Get-Service -Name $ServiceName).WaitForStatus('Running', [TimeSpan]::FromSeconds(20))
    $Listening = $false
    for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
        if (@(Get-PortListener -CandidatePort $SelectedPort).Count -gt 0) {
            $Listening = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $Listening) { throw "Le service est démarré mais TCP/$SelectedPort n'écoute pas." }

    $ServiceState = [ordered]@{
        schema_version = 1
        service_name = $ServiceName
        account = $ServiceAccount
        port = $SelectedPort
        firewall_profiles = @('Domain', 'Private')
        installed_at = [DateTimeOffset]::UtcNow.ToString('o')
    }
    $Temporary = "$StatePath.tmp"
    [IO.File]::WriteAllText($Temporary, ($ServiceState | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $Temporary -Destination $StatePath -Force
    Write-MarvinHttpsEvent -Action 'service-install' -Result 'success' -Context @{
        service_name = $ServiceName
        port = $SelectedPort
        account = 'LocalService'
        firewall_profiles = 'Domain,Private'
    }
} catch {
    Get-Service -Name $ServiceName -ErrorAction SilentlyContinue | Stop-Service -Force -ErrorAction SilentlyContinue
    & sc.exe delete $ServiceName 2>$null | Out-Null
    Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
    if ($null -ne $PreviousConfig) {
        [IO.File]::WriteAllText($Config, $PreviousConfig, [Text.UTF8Encoding]::new($false))
    }
    if ($null -ne $PreviousState) {
        [IO.File]::WriteAllText((Join-Path $Runtime 'state.json'), $PreviousState, [Text.UTF8Encoding]::new($false))
    }
    if ($UnmanagedGatewayWasRunning -and $null -ne $PreviousConfig) {
        Start-Process -FilePath $Caddy -ArgumentList @('run', '--config', $Config) `
            -WorkingDirectory $Runtime -WindowStyle Hidden | Out-Null
    }
    Write-MarvinHttpsEvent -Action 'service-install' -Result 'failure' -Context @{
        service_name = $ServiceName
        port = $SelectedPort
        error_type = $_.Exception.GetType().Name
    }
    throw
}

$Port = $SelectedPort
Get-ServiceSnapshot
