[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$PreferredPort = 8890
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$StateDirectory = Join-Path $Root 'runtime\searxng'
$StatePath = Join-Path $StateDirectory 'port.txt'

function Test-LoopbackPortAvailable {
    param([Parameter(Mandatory = $true)][int]$Port)
    $Listener = $null
    try {
        $Listener = [System.Net.Sockets.TcpListener]::new(
            [System.Net.IPAddress]::Loopback,
            $Port
        )
        $Listener.Start()
        return $true
    } catch [System.Net.Sockets.SocketException] {
        # Couvre aussi WSAEACCES lorsque Hyper-V/WSL réserve une plage TCP.
        return $false
    } finally {
        if ($null -ne $Listener) { $Listener.Stop() }
    }
}

$Candidates = [System.Collections.Generic.List[int]]::new()
if (Test-Path -LiteralPath $StatePath) {
    $Stored = 0
    if ([int]::TryParse((Get-Content -LiteralPath $StatePath -Raw).Trim(), [ref]$Stored)) {
        if ($Stored -ge 1024 -and $Stored -le 65535) { $Candidates.Add($Stored) }
    }
}
$Candidates.Add($PreferredPort)
foreach ($Port in 8390..8499) { $Candidates.Add($Port) }
foreach ($Port in 9390..9499) { $Candidates.Add($Port) }

$Selected = $null
foreach ($Port in @($Candidates | Select-Object -Unique)) {
    if (Test-LoopbackPortAvailable -Port $Port) {
        $Selected = $Port
        break
    }
}
if ($null -eq $Selected) {
    throw 'Aucun port local disponible pour SearXNG dans les plages prises en charge.'
}

New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null
$Temporary = "$StatePath.$PID.tmp"
[System.IO.File]::WriteAllText($Temporary, [string]$Selected)
Move-Item -LiteralPath $Temporary -Destination $StatePath -Force
Write-Output $Selected
