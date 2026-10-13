[CmdletBinding(SupportsShouldProcess = $true)]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-WslBounded {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [ValidateRange(5, 900)][int]$TimeoutSeconds = 30
    )
    $Stdout = [IO.Path]::GetTempFileName()
    $Stderr = [IO.Path]::GetTempFileName()
    try {
        $Process = Start-Process -FilePath 'wsl.exe' -ArgumentList $Arguments -PassThru -WindowStyle Hidden -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
        $null = $Process.Handle
        if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
            & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
            return [ordered]@{ exit_code = 124; output = 'timeout' }
        }
        $Process.WaitForExit()
        $Process.Refresh()
        return [ordered]@{
            exit_code = [int]$Process.ExitCode
            output = (([IO.File]::ReadAllText($Stdout) + [IO.File]::ReadAllText($Stderr)) -replace "`0", '').Trim()
        }
    } finally {
        Remove-Item -LiteralPath $Stdout, $Stderr -Force -ErrorAction SilentlyContinue
    }
}

function Test-WslVersionResult($Result) {
    if ([int]$Result.exit_code -ne 0) { return $false }
    # Le lanceur Windows peut afficher une aide d'installation et retourner 0.
    # Seule la ligne de version WSL (anglais/francais et autres locales) est recevable.
    $Match = [regex]::Match([string]$Result.output, '(?im)^[^\r\n]*(?<![A-Za-z])WSL(?![A-Za-z])[^\r\n:]*:\s*(\d+\.\d+\.\d+(?:\.\d+)?)')
    if (-not $Match.Success) { return $false }
    return [version]$Match.Groups[1].Value -ge [version]'2.1.5'
}

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Cette operation exige une elevation administrateur.'
}

$Required = @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform')
$Changed = $false
foreach ($FeatureName in $Required) {
    $Feature = Get-WindowsOptionalFeature -Online -FeatureName $FeatureName -ErrorAction Stop
    if ($Feature.State -ne 'Enabled') {
        if ($PSCmdlet.ShouldProcess($FeatureName, 'Activer la fonctionnalite Windows')) {
            $Result = Enable-WindowsOptionalFeature -Online -FeatureName $FeatureName -All -NoRestart -ErrorAction Stop
            if ($Result.RestartNeeded) { $Changed = $true }
        }
    }
}

$Ready = $true
foreach ($FeatureName in $Required) {
    $Feature = Get-WindowsOptionalFeature -Online -FeatureName $FeatureName -ErrorAction Stop
    if ($Feature.State -notin @('Enabled', 'EnablePending')) { $Ready = $false }
}
if (-not $Ready) { throw 'Les prerequis WSL 2 ne sont pas actives.' }

$Pending = $Changed
foreach ($FeatureName in $Required) {
    if ((Get-WindowsOptionalFeature -Online -FeatureName $FeatureName -ErrorAction Stop).State -eq 'EnablePending') {
        $Pending = $true
    }
}
if ($Pending) {
    Write-Output 'Prerequis WSL 2 actives; redemarrage Windows requis.'
    exit 3010
}
$Version = Invoke-WslBounded -Arguments @('--version') -TimeoutSeconds 30
if (-not (Test-WslVersionResult $Version)) {
    if ($PSCmdlet.ShouldProcess('WSL', 'Installer le runtime sans distribution Linux')) {
        $Install = Invoke-WslBounded -Arguments @('--install', '--no-distribution', '--web-download') -TimeoutSeconds 600
        if ([int]$Install.exit_code -notin @(0, 3010)) {
            $Detail = (([string]$Install.output -split '\r?\n' | Where-Object {$_ -notmatch '(?i)token|password|secret|cookie|authorization|[?&](sig|se|sv|sp)='}) -join ' ')
            if ($Detail.Length -gt 1500) { $Detail = $Detail.Substring(0,1500) }
            throw "Installation du runtime WSL echouee avec le code $($Install.exit_code): $Detail"
        }
    }
    Write-Output 'Runtime WSL installe; redemarrage Windows requis.'
    exit 3010
}
Write-Output 'Prerequis WSL 2 actifs.'
exit 0
