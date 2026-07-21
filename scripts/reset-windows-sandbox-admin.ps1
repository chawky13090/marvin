[CmdletBinding(SupportsShouldProcess)]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$service = Get-Service -Name 'CmService' -ErrorAction Stop
if ($PSCmdlet.ShouldProcess('CmService', 'Redemarrer le gestionnaire Windows Sandbox')) {
    Restart-Service -Name 'CmService' -Force -ErrorAction Stop
    $service.WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
}

$deadline = [DateTimeOffset]::Now.AddSeconds(30)
do {
    $sandboxMemory = Get-Process -Name 'vmmemWindowsSandbox' -ErrorAction SilentlyContinue
    if (-not $sandboxMemory) {
        Write-Output '[OK] Windows Sandbox reinitialise; aucun vmmem orphelin.'
        exit 0
    }
    Start-Sleep -Milliseconds 500
} while ([DateTimeOffset]::Now -lt $deadline)

Write-Error 'CmService est actif mais vmmemWindowsSandbox reste present.'
exit 1
