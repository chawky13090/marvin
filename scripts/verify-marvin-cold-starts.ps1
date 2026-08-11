[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [ValidateRange(1, 10)][int]$Cycles = 5,
    [ValidateRange(60, 300)][int]$StartupTimeoutSeconds = 180
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Results = @()

if (-not $PSCmdlet.ShouldProcess('Marvin', "$Cycles redémarrages froids vérifiés")) { exit 0 }

for ($Cycle = 1; $Cycle -le $Cycles; $Cycle++) {
    $StartedAt = Get-Date
    $Raw = & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File (Join-Path $PSScriptRoot 'restart-marvin.ps1') `
        -StartupTimeoutSeconds $StartupTimeoutSeconds
    if ($LASTEXITCODE -ne 0) {
        throw "Cycle $Cycle en échec : $($Raw -join ' ')"
    }
    $Status = ($Raw | Select-Object -Last 1) | ConvertFrom-Json
    $Coding = Invoke-WebRequest -UseBasicParsing `
        -Uri 'http://127.0.0.1:8005/api/coding/overview' -TimeoutSec 10
    $VmLab = Invoke-WebRequest -UseBasicParsing `
        -Uri 'http://127.0.0.1:8005/api/vm-lab/status' -TimeoutSec 10
    if ($Status.state -notin @('ready', 'degraded') -or
        $Status.readiness.code_workspace.ready -ne $true -or
        $Status.readiness.vm_lab.ready -ne $true -or
        $Coding.StatusCode -ne 200 -or $VmLab.StatusCode -ne 200) {
        throw "Cycle $Cycle déclaré prêt sans readiness complète."
    }
    $Results += [ordered]@{
        cycle = $Cycle
        state = $Status.state
        duration_ms = [math]::Round(((Get-Date) - $StartedAt).TotalMilliseconds)
        code_workspace_http = $Coding.StatusCode
        vm_lab_http = $VmLab.StatusCode
    }
}

$Report = [ordered]@{
    schema = 'marvin.cold-start-readiness/1.0'
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
    cycles = $Results
    passed = @($Results).Count -eq $Cycles
}
$ReportPath = Join-Path $Root 'artifacts\cold-start-readiness-report.json'
$Parent = Split-Path -Parent $ReportPath
if (-not (Test-Path -LiteralPath $Parent)) { New-Item -ItemType Directory -Path $Parent | Out-Null }
$Temporary = "$ReportPath.tmp"
$Report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Temporary -Encoding UTF8
Move-Item -LiteralPath $Temporary -Destination $ReportPath -Force
$Report | ConvertTo-Json -Compress -Depth 6
