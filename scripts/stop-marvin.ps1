[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Ports = @(3000, 8005, 8443)
$Stopped = @()

function Test-MarvinProcess {
    param([Parameter(Mandatory = $true)][int]$Id)
    $CurrentId = $Id
    for ($Depth = 0; $Depth -lt 5 -and $CurrentId -gt 0; $Depth++) {
        $Candidate = Get-CimInstance Win32_Process -Filter "ProcessId = $CurrentId" -ErrorAction SilentlyContinue
        if ($null -eq $Candidate) { return $false }
        $Identity = "{0} {1}" -f [string]$Candidate.ExecutablePath, [string]$Candidate.CommandLine
        if ($Identity -like "*$ProjectRoot*") { return $true }
        $CurrentId = [int]$Candidate.ParentProcessId
    }
    return $false
}

foreach ($Port in $Ports) {
    $Connections = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    foreach ($Connection in $Connections) {
        $ProcessId = [int]$Connection.OwningProcess
        $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
        if ($null -eq $Process) { continue }
        if (-not (Test-MarvinProcess -Id $ProcessId)) {
            Write-Warning "Port $Port ignoré : le processus $ProcessId n'appartient pas à Marvin."
            continue
        }
        if ($PSCmdlet.ShouldProcess("PID $ProcessId sur le port $Port", 'Arrêter le processus Marvin')) {
            Stop-Process -Id $ProcessId -Force -ErrorAction Stop
            $Stopped += $ProcessId
        }
    }
}

[pscustomobject]@{
    success = $true
    stopped_process_ids = @($Stopped | Sort-Object -Unique)
    preserved_ollama = $true
} | ConvertTo-Json -Compress
