[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$EnableSandbox,
    [string]$LogPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Repair-SandboxPrerequisites {
    [CmdletBinding(SupportsShouldProcess)]
    param()

    $hvHost = Get-Service -Name 'HvHost' -ErrorAction SilentlyContinue
    if (-not $hvHost) {
        throw 'Le service HvHost est absent. Reparez Windows avec DISM avant d activer Sandbox.'
    }

    $hvHostPath = 'HKLM:\SYSTEM\CurrentControlSet\Services\HvHost'
    $hvHostRegistry = Get-ItemProperty -LiteralPath $hvHostPath -ErrorAction Stop
    if ([int]$hvHostRegistry.Start -eq 4) {
        if ($PSCmdlet.ShouldProcess('HvHost', 'Retablir le demarrage manuel requis par Windows Sandbox')) {
            Set-Service -Name 'HvHost' -StartupType Manual
            Write-Output '[REPAIRED] HvHost : Disabled -> Manual.'
        }
    }

    $hvHostRegistry = Get-ItemProperty -LiteralPath $hvHostPath -ErrorAction Stop
    if ([int]$hvHostRegistry.Start -eq 4) {
        throw 'HvHost reste desactive. Windows Sandbox echouerait avec 0x800706D9.'
    }

    foreach ($serviceName in @('RpcSs', 'BFE', 'MpsSvc')) {
        $service = Get-Service -Name $serviceName -ErrorAction Stop
        if ($service.Status -ne 'Running') {
            throw "Le service requis $serviceName n est pas demarre. Activation abandonnee."
        }
    }

    # VBS/HVCI (Isolation du noyau) reste volontairement hors perimetre.
    Write-Output '[OK] Prerequis RPC, pare-feu et HvHost valides. VBS/HVCI non modifie.'
}

try {
    if ($EnableSandbox) {
        Repair-SandboxPrerequisites -Confirm:$false
    }

    $feature = Get-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM
    Write-Output "Windows Sandbox : $($feature.State)"

    if ($feature.State -eq 'Enabled') {
        $sandbox = Join-Path $env:SystemRoot 'System32\WindowsSandbox.exe'
        if (-not (Test-Path -LiteralPath $sandbox)) {
            Write-Output 'La fonctionnalité est active mais le redémarrage Windows reste requis.'
            exit 3010
        }
        Write-Output '[OK] Runner Windows Sandbox disponible.'
        exit 0
    }

    if (-not $EnableSandbox) {
        Write-Output 'Windows Sandbox est désactivé.'
        Write-Output 'Relancez en administrateur avec -EnableSandbox. Un redémarrage Windows sera requis.'
        exit 2
    }

    if (-not $PSCmdlet.ShouldProcess(
        'Containers-DisposableClientVM',
        'Activer Windows Sandbox'
    )) {
        exit 0
    }

    $result = Enable-WindowsOptionalFeature -Online `
        -FeatureName Containers-DisposableClientVM `
        -All `
        -NoRestart

    $featureAfter = Get-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM
    Write-Output "État après activation : $($featureAfter.State)"
    Write-Output "Redémarrage requis : $($result.RestartNeeded)"
    $sandboxAfter = Join-Path $env:SystemRoot 'System32\WindowsSandbox.exe'
    if ($result.RestartNeeded -or -not (Test-Path -LiteralPath $sandboxAfter)) {
        Write-Output 'Redémarrez Windows avant d’utiliser Test Forge Windows.'
        exit 3010
    }
}
catch {
    if ($LogPath) {
        [ordered]@{
            at = [DateTimeOffset]::Now.ToString('o')
            type = $_.Exception.GetType().FullName
            message = $_.Exception.Message
            category = [string]$_.CategoryInfo
            fully_qualified_error_id = $_.FullyQualifiedErrorId
        } | ConvertTo-Json -Depth 4 |
            Set-Content -LiteralPath $LogPath -Encoding UTF8
    }
    throw
}
