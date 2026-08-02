[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runtime = Join-Path $Root 'runtime\https'
$StatePath = Join-Path $Runtime 'state.json'
$Caddy = Join-Path $Runtime 'caddy.exe'
$Config = Join-Path $Runtime 'caddy.json'
if (-not (Test-Path -LiteralPath $Caddy -PathType Leaf)) { exit 0 }

$Port = 8443
if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
    $State = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
    $Candidate = 0
    if ([int]::TryParse([string]$State.port, [ref]$Candidate) -and $Candidate -ge 443 -and $Candidate -le 65535) {
        $Port = $Candidate
    }
}

$Service = Get-Service -Name 'MarvinHttpsGateway' -ErrorAction SilentlyContinue
if ($null -ne $Service) {
    if ($Service.Status -ne 'Running') {
        try {
            Start-Service -Name 'MarvinHttpsGateway'
            $Service.WaitForStatus('Running', [TimeSpan]::FromSeconds(20))
        } catch {
            Write-Error 'Le service HTTPS Marvin est installé mais arrêté. Relancez son installation en administrateur.'
            exit 2
        }
    }
} else {
    $AdminReady = $null -ne (Get-NetTCPConnection -LocalPort 2019 -State Listen -ErrorAction SilentlyContinue)
    if (-not $AdminReady) {
        Start-Process -FilePath $Caddy -ArgumentList @('run', '--config', $Config) `
            -WorkingDirectory $Runtime -WindowStyle Hidden | Out-Null
    }
}

for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
    if ($null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
        Write-Output "https://localhost:$Port"
        exit 0
    }
    Start-Sleep -Milliseconds 500
}
Write-Error "La passerelle HTTPS Marvin n'écoute pas sur TCP/$Port."
exit 1
