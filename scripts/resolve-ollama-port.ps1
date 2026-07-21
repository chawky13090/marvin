[CmdletBinding()]
param(
    [int[]]$CandidatePorts = @(11434, 12434, 13434, 14434, 15434)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-ExcludedTcpRanges {
    $ranges = @()
    $lines = & netsh interface ipv4 show excludedportrange protocol=tcp 2>$null
    foreach ($line in $lines) {
        if ($line -match '^\s*(\d+)\s+(\d+)(?:\s+\*)?\s*$') {
            $ranges += [pscustomobject]@{
                Start = [int]$Matches[1]
                End   = [int]$Matches[2]
            }
        }
    }
    return $ranges
}

function Test-IsExcluded {
    param(
        [Parameter(Mandatory)]
        [int]$Port,
        [Parameter(Mandatory)]
        [object[]]$Ranges
    )

    foreach ($range in $Ranges) {
        if ($Port -ge $range.Start -and $Port -le $range.End) {
            return $true
        }
    }
    return $false
}

function Test-OllamaApi {
    param(
        [Parameter(Mandatory)]
        [int]$Port
    )

    try {
        $response = Invoke-WebRequest `
            -UseBasicParsing `
            -Uri ("http://127.0.0.1:{0}/api/tags" -f $Port) `
            -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Test-LocalBind {
    param(
        [Parameter(Mandatory)]
        [int]$Port
    )

    $listener = $null
    try {
        $address = [System.Net.IPAddress]::Parse('127.0.0.1')
        $listener = [System.Net.Sockets.TcpListener]::new($address, $Port)
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $listener) {
            $listener.Stop()
        }
    }
}

$excludedRanges = @(Get-ExcludedTcpRanges)

foreach ($port in $CandidatePorts) {
    if ($port -lt 1024 -or $port -gt 65535) {
        continue
    }

    if (Test-OllamaApi -Port $port) {
        Write-Output $port
        exit 0
    }

    if (Test-IsExcluded -Port $port -Ranges $excludedRanges) {
        continue
    }

    if (Test-LocalBind -Port $port) {
        Write-Output $port
        exit 0
    }
}

Write-Error ("Aucun port Ollama disponible parmi : {0}" -f ($CandidatePorts -join ', '))
exit 1
