[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [ValidateRange(60, 300)][int]$StartupTimeoutSeconds = 180
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$PolicyPath = Join-Path $Root 'benchmarks\conversation-history\td015-closure-policy.json'
$FreezePath = Join-Path $Root 'benchmarks\conversation-history\td015-closure-freeze-v2.json'
$ResultPath = Join-Path $Root 'benchmarks\conversation-history\td015-closure-result.json'
$Python = Join-Path $Root 'backend\.venv\Scripts\python.exe'

if (-not $PSCmdlet.ShouldProcess('Marvin', '3 redémarrages froids et validation TD-015')) { exit 0 }
if (-not (Test-Path -LiteralPath $FreezePath)) { throw 'Le gel TD-015 est absent.' }
if (Test-Path -LiteralPath $ResultPath) { throw 'Le résultat TD-015 existe déjà et reste immuable.' }

$Policy = Get-Content -Raw -LiteralPath $PolicyPath | ConvertFrom-Json
$Freeze = Get-Content -Raw -LiteralPath $FreezePath | ConvertFrom-Json
if ($Policy.execution_authorized -ne $false -or $Policy.result_publication_authorized -ne $false) {
    throw 'La politique historique ne peut pas autoriser sa propre exécution.'
}
if ($Freeze.execution_authorized -ne $true -or $Freeze.result_publication_authorized -ne $true) {
    throw 'Le manifeste de gel doit autoriser explicitement la campagne et sa publication.'
}
$PolicyHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $PolicyPath).Hash.ToLowerInvariant()
if ($PolicyHash -ne [string]$Freeze.policy_sha256) {
    throw 'La politique differe du manifeste de gel.'
}
if ([int]$Policy.cold_start.startup_timeout_seconds -ne $StartupTimeoutSeconds) {
    throw 'Le timeout demandé diverge du contrat gelé.'
}
foreach ($Entry in $Freeze.source_hashes.PSObject.Properties) {
    $Path = Join-Path $Root $Entry.Name
    $Actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($Actual -ne [string]$Entry.Value) { throw "Source modifiée après gel : $($Entry.Name)" }
}

$RunRoot = Join-Path $Root ('artifacts\td015-closure-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $RunRoot | Out-Null
$Cycles = @()
try {
    for ($Cycle = 1; $Cycle -le [int]$Policy.cold_start.required_consecutive_cycles; $Cycle++) {
        $StartedAt = Get-Date
        $Raw = & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File (Join-Path $PSScriptRoot 'restart-marvin.ps1') `
            -StartupTimeoutSeconds $StartupTimeoutSeconds
        if ($LASTEXITCODE -ne 0) { throw "Redémarrage froid $Cycle en échec : $($Raw -join ' ')" }
        $Startup = ($Raw | Select-Object -Last 1) | ConvertFrom-Json
        if ($Startup.state -ne $Policy.cold_start.state_must_equal -or
            $Startup.readiness.code_workspace.ready -ne $true -or
            $Startup.readiness.vm_lab.ready -ne $true) {
            throw "Readiness incomplète au cycle $Cycle."
        }
        $CyclePath = Join-Path $RunRoot ("cycle-{0}.json" -f $Cycle)
        & $Python (Join-Path $PSScriptRoot 'verify_td015_cycle.py') `
            --policy $PolicyPath --cycle $Cycle --output $CyclePath | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Vérification fonctionnelle $Cycle en échec." }
        $Functional = Get-Content -Raw -LiteralPath $CyclePath | ConvertFrom-Json
        $Cycles += [ordered]@{
            cycle = $Cycle
            state = [string]$Startup.state
            cycle_total_ms = [math]::Round(((Get-Date) - $StartedAt).TotalMilliseconds)
            startup_wait_ms = [int64]$Startup.startup_wait_ms
            stop_duration_ms = [int64]$Startup.stop_duration_ms
            code_workspace_http = 200
            vm_lab_http = 200
            functional = $Functional
        }
    }
    $TargetHashes = @($Cycles | ForEach-Object { $_.functional.target_id_sha256 } | Select-Object -Unique)
    if ($TargetHashes.Count -ne 1) { throw 'La conversation cible a changé entre les cycles.' }
    $Report = [ordered]@{
        schema = 'marvin.td015-closure-result/1.0'
        generated_at = (Get-Date).ToUniversalTime().ToString('o')
        policy_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $PolicyPath).Hash.ToLowerInvariant()
        freeze_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $FreezePath).Hash.ToLowerInvariant()
        source_commit = [string]$Freeze.source_commit
        cycles = $Cycles
        required_consecutive_cycles = [int]$Policy.cold_start.required_consecutive_cycles
        data_modified = $false
        conversation_identifier_plaintext_published = $false
        passed = @($Cycles).Count -eq [int]$Policy.cold_start.required_consecutive_cycles
    }
    $Temporary = "$ResultPath.tmp"
    $Report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Temporary -Encoding UTF8
    Move-Item -LiteralPath $Temporary -Destination $ResultPath
    $Report | ConvertTo-Json -Compress -Depth 12
} catch {
    $AbortPath = Join-Path $RunRoot 'aborted.json'
    [ordered]@{
        schema = 'marvin.td015-closure-abort/1.0'
        generated_at = (Get-Date).ToUniversalTime().ToString('o')
        completed_cycles = @($Cycles).Count
        error = $_.Exception.Message
        result_published = $false
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $AbortPath -Encoding UTF8
    throw
}
