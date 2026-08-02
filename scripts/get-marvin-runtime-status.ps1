[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))

function Invoke-SafeJsonProbe {
    param([Parameter(Mandatory = $true)][string]$Uri, [int]$TimeoutSeconds = 3)
    try {
        return Invoke-RestMethod -Uri $Uri -TimeoutSec $TimeoutSeconds
    } catch {
        return $null
    }
}

$Health = Invoke-SafeJsonProbe -Uri 'http://127.0.0.1:8005/api/health'
$Lan = Invoke-SafeJsonProbe -Uri 'http://127.0.0.1:8005/api/auth/lan/status'
$Frontend = Invoke-SafeJsonProbe -Uri 'http://127.0.0.1:3000/api/status'
$HttpsPort = 8443
$HttpsStatePath = Join-Path $Root 'runtime\https\state.json'
if (Test-Path -LiteralPath $HttpsStatePath -PathType Leaf) {
    try { $HttpsPort = [int](Get-Content -Raw -LiteralPath $HttpsStatePath | ConvertFrom-Json).port } catch { $HttpsPort = 8443 }
}
$Https = $false
try {
    $Https = (Invoke-WebRequest -UseBasicParsing -Uri "https://127.0.0.1:$HttpsPort/" `
        -TimeoutSec 4 -SkipCertificateCheck).StatusCode -eq 200
} catch {
    # Windows PowerShell 5.1 ne possède pas SkipCertificateCheck. La présence
    # du listener et de l'admin Caddy reste vérifiée sans désactiver TLS globalement.
    $Https = $null -ne (Get-NetTCPConnection -LocalPort $HttpsPort -State Listen -ErrorAction SilentlyContinue)
}

$OllamaPort = 0
$Ollama = $false
foreach ($Candidate in @(11434, 12434, 13434, 14434, 15434)) {
    if ($null -ne (Invoke-SafeJsonProbe -Uri "http://127.0.0.1:$Candidate/api/tags" -TimeoutSeconds 2)) {
        $OllamaPort = $Candidate
        $Ollama = $true
        break
    }
}

$SearxngPort = 0
$SearxngState = Join-Path $Root 'runtime\searxng\port.txt'
if (Test-Path -LiteralPath $SearxngState) {
    [void][int]::TryParse((Get-Content -LiteralPath $SearxngState -Raw).Trim(), [ref]$SearxngPort)
}
$Searxng = $SearxngPort -gt 0 -and $null -ne (
    Invoke-SafeJsonProbe -Uri "http://127.0.0.1:$SearxngPort/config"
)

$CoreReady = $null -ne $Health -and $null -ne $Frontend
$Degraded = $CoreReady -and (-not $Ollama -or -not $Searxng -or -not $Https)
$Overall = if (-not $CoreReady) { 'stopped_or_failed' } elseif ($Degraded) { 'degraded' } else { 'ready' }

[ordered]@{
    timestamp = (Get-Date).ToUniversalTime().ToString('o')
    overall = $Overall
    core = [ordered]@{
        backend = $null -ne $Health
        frontend = $null -ne $Frontend
        version = if ($null -ne $Health) { [string]$Health.version } else { $null }
        tools = if ($null -ne $Health) { [int]$Health.tools_count } else { 0 }
    }
    dependencies = [ordered]@{
        ollama = $Ollama
        ollama_port = $OllamaPort
        searxng = $Searxng
        searxng_port = $SearxngPort
        https = $Https
        https_port = $HttpsPort
    }
    lan = [ordered]@{
        authenticated = $null -ne $Lan -and $Lan.authenticated -eq $true
        pairing_required = $null -ne $Lan -and $Lan.required -eq $true
        transport_secure = $null -ne $Lan -and $Lan.transport_secure -eq $true
    }
    coordination = [ordered]@{
        startup_lock = Test-Path -LiteralPath (Join-Path $Root 'runtime\lifecycle\startup.lock')
        stop_requested = Test-Path -LiteralPath (Join-Path $Root 'runtime\lifecycle\stop.requested')
    }
} | ConvertTo-Json -Depth 6
