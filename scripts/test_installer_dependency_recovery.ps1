Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Execute the actual installer stage bodies, but replace external programs with
# deterministic fault injection. Never load or execute the installer entrypoint.
$Source = Join-Path $PSScriptRoot 'install-marvin-oneclick.ps1'
$Tokens = $null
$Errors = $null
$Ast = [System.Management.Automation.Language.Parser]::ParseFile($Source, [ref]$Tokens, [ref]$Errors)
if ($Errors.Count) { throw 'Installer source cannot be parsed.' }
$StageActions = @{}
foreach ($Name in @('backend_dependencies', 'frontend_dependencies')) {
    $Commands = @($Ast.FindAll({
        param($Node)
        $Node -is [System.Management.Automation.Language.CommandAst] -and
        $Node.GetCommandName() -eq 'Invoke-InstallStage'
    }, $true))
    foreach ($Command in $Commands) {
        $Elements = $Command.CommandElements
        if ($Elements.Count -ge 5 -and $Elements[2].Value -eq $Name) {
            if ($StageActions.ContainsKey($Name)) { throw 'Duplicate stage.' }
            $StageActions[$Name] = $Elements[4].ScriptBlock.GetScriptBlock()
        }
    }
    if (-not $StageActions.ContainsKey($Name)) { throw "Stage missing: $Name" }
}

$Root = Join-Path ([IO.Path]::GetTempPath()) ('marvin-dependency-recovery-' + [guid]::NewGuid().ToString('N'))
$Root = [IO.Path]::GetFullPath($Root)
$TemporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
if (-not $Root.StartsWith($TemporaryRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe test root.' }
$ProjectRoot = $Root
$DownloadRoot = Join-Path $Root 'downloads'
$script:PythonPath = Join-Path $Root 'fake-python.exe'
$script:NodePath = Join-Path $Root 'node.exe'
$PreviousNpmCache = $env:npm_config_cache
$script:CallCount = 0
$script:FailAt = 1
$script:Calls = @()

function Invoke-External {
    param([string]$FilePath, [string[]]$ArgumentList)
    $script:CallCount++
    $script:Calls += ($ArgumentList -join ' ')
    if ($ArgumentList.Count -ge 3 -and $ArgumentList[1] -eq 'venv') {
        $Scripts = Join-Path $ArgumentList[2] 'Scripts'
        New-Item -ItemType Directory -Path $Scripts -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $Scripts 'partial.txt'), 'synthetic incomplete environment')
    } elseif ($FilePath -like '*npm.cmd') {
        New-Item -ItemType Directory -Path (Join-Path $ProjectRoot 'node_modules') -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $ProjectRoot 'node_modules/partial.txt'), 'synthetic incomplete modules')
    }
    if ($script:CallCount -eq $script:FailAt) { throw 'synthetic_network_interruption' }
    return 0
}

$Cases = 0
try {
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $Root 'npm.cmd'), 'synthetic; never executed')
    foreach ($Name in @('backend_dependencies', 'frontend_dependencies')) {
        $Relative = if ($Name -eq 'backend_dependencies') { 'backend/.venv' } else { 'node_modules' }
        $Target = Join-Path $Root $Relative
        $FailurePoints = if ($Name -eq 'backend_dependencies') { @(1, 2, 3, 4) } else { @(1, 2) }
        foreach ($Existing in @($false, $true)) {
            foreach ($FailurePoint in $FailurePoints) {
                if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Recurse -Force }
                if ($Existing) {
                    New-Item -ItemType Directory -Path $Target -Force | Out-Null
                    [IO.File]::WriteAllText((Join-Path $Target 'original.txt'), 'previous working environment')
                }
                for ($Replay = 1; $Replay -le 2; $Replay++) {
                    $script:CallCount = 0
                    $script:Calls = @()
                    $script:FailAt = $FailurePoint
                    $Failed = $false
                    try { & $StageActions[$Name] } catch {
                        if ($_.Exception.Message -ne 'synthetic_network_interruption') { throw }
                        $Failed = $true
                    }
                    if (-not $Failed) { throw 'Injected failure was swallowed.' }
                    if ($script:CallCount -ne $FailurePoint) { throw 'Unexpected execution after failure.' }
                    if ($Existing) {
                        if ([IO.File]::ReadAllText((Join-Path $Target 'original.txt')) -ne 'previous working environment') { throw 'Original not restored.' }
                        if (@(Get-ChildItem -LiteralPath $Target -Recurse -File).Count -ne 1) { throw 'Partial content leaked into restored environment.' }
                    } elseif (Test-Path -LiteralPath $Target) { throw 'Incomplete fresh environment retained.' }
                    if (@(Get-ChildItem -LiteralPath (Split-Path $Target -Parent) -Filter ((Split-Path $Target -Leaf) + '.rollback-*')).Count) { throw 'Rollback directory leaked.' }
                    $Cases++
                }
            }
        }
    }
    # A healthy retry must also be possible; a guard that rejects every run is
    # not a recovery mechanism. This is a synthetic npm success, not real npm.
    $script:CallCount = 0
    $script:FailAt = -1
    & $StageActions['frontend_dependencies']
    if ($script:CallCount -ne 2) { throw 'Healthy frontend retry did not finish both checks.' }
    if (Test-Path -LiteralPath (Join-Path $Root 'node_modules/original.txt')) { throw 'Old environment remained active after success.' }
    if (-not (Test-Path -LiteralPath (Join-Path $Root 'node_modules/partial.txt'))) { throw 'New synthetic environment missing.' }
    Write-Output "Installer dependency recovery OK - $Cases injected failures/replays, original bytes restored, no partial environments."
} finally {
    $env:npm_config_cache = $PreviousNpmCache
    if (Test-Path -LiteralPath $Root) { Remove-Item -LiteralPath $Root -Recurse -Force }
}
