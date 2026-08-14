[CmdletBinding()]
param(
    [ValidateSet('Path', 'Json')]
    [string]$Output = 'Path',
    [string]$ExplicitPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$MinimumVersion = [Version]'3.12.0'
$MaximumVersionExclusive = [Version]'3.14.0'
$RejectedPathPatterns = @(
    '\\.cache\\codex-runtimes\\',
    '\\AppData\\Local\\Temp\\',
    '\\WindowsApps\\python(?:3)?\.exe$'
)

function Test-RejectedPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    foreach ($Pattern in $RejectedPathPatterns) {
        if ($Path -match $Pattern) { return $true }
    }
    return $false
}

function Add-Candidate {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[object]]$List,
        [string]$Path,
        [string]$Source
    )
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    try { $Resolved = [IO.Path]::GetFullPath($Path.Trim()) } catch { return }
    foreach ($Existing in $List) {
        if ([string]$Existing.Path -eq $Resolved) { return }
    }
    $List.Add([pscustomobject]@{ Path = $Resolved; Source = $Source })
}

function Get-PythonProbe {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    if (Test-RejectedPath -Path $Path) { return $null }
    try {
        $Raw = & $Path -c "import json,platform,sys; print(json.dumps({'version':platform.python_version(),'architecture':platform.architecture()[0],'executable':sys.executable,'base_executable':getattr(sys,'_base_executable',sys.executable)}))" 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($Raw -join ''))) { return $null }
        $Probe = ($Raw -join '') | ConvertFrom-Json
        $Version = [Version]$Probe.version
        $Executable = [IO.Path]::GetFullPath([string]$Probe.executable)
        $BaseExecutable = [IO.Path]::GetFullPath([string]$Probe.base_executable)
        if ($Version -lt $MinimumVersion -or $Version -ge $MaximumVersionExclusive) { return $null }
        if ([string]$Probe.architecture -ne '64bit') { return $null }
        if ((Test-RejectedPath -Path $Executable) -or (Test-RejectedPath -Path $BaseExecutable)) { return $null }
        if (-not (Test-Path -LiteralPath $BaseExecutable -PathType Leaf)) { return $null }
        return [pscustomobject]@{
            path = $Executable
            base_executable = $BaseExecutable
            version = $Version.ToString()
            architecture = [string]$Probe.architecture
        }
    } catch {
        return $null
    }
}

$Candidates = [System.Collections.Generic.List[object]]::new()
Add-Candidate -List $Candidates -Path $ExplicitPath -Source 'parameter'
Add-Candidate -List $Candidates -Path $env:MARVIN_PYTHON -Source 'environment'

if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($Selector in @('-3.13', '-3.12')) {
        try {
            $Resolved = & py $Selector -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Add-Candidate -List $Candidates -Path (($Resolved | Select-Object -Last 1) -as [string]) -Source ("launcher " + $Selector)
            }
        } catch {}
    }
}

foreach ($Known in @(
    (Join-Path ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))) 'runtime\managed\python\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
)) {
    Add-Candidate -List $Candidates -Path $Known -Source 'official-user-install'
}

foreach ($Command in @(Get-Command python -All -ErrorAction SilentlyContinue)) {
    Add-Candidate -List $Candidates -Path $Command.Source -Source 'PATH'
}

$Selected = $null
foreach ($Candidate in $Candidates) {
    $Probe = Get-PythonProbe -Path $Candidate.Path
    if ($null -eq $Probe) { continue }
    $Selected = [ordered]@{
        schema_version = 1
        path = $Probe.path
        base_executable = $Probe.base_executable
        version = $Probe.version
        architecture = $Probe.architecture
        source = $Candidate.Source
        supported_minimum = $MinimumVersion.ToString()
        supported_maximum_exclusive = $MaximumVersionExclusive.ToString()
        portable = $true
    }
    break
}

if ($null -eq $Selected) {
    Write-Error 'Aucun Python 64 bits persistant et compatible (3.12 ou 3.13) n a été trouvé.'
    exit 2
}

if ($Output -eq 'Json') {
    $Selected | ConvertTo-Json -Compress
} else {
    [string]$Selected.path
}
