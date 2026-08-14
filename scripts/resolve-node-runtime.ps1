[CmdletBinding()]
param(
    [ValidateSet('Path', 'Json')]
    [string]$Output = 'Path'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Candidates = @(
    (Join-Path $ProjectRoot 'runtime\managed\node\node.exe')
)
$PathNode = Get-Command node.exe -ErrorAction SilentlyContinue
if ($null -ne $PathNode -and $PathNode.Source) {
    $Candidates += [string]$PathNode.Source
}

foreach ($Candidate in $Candidates) {
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { continue }
    try {
        $Probe = & $Candidate -e "console.log(JSON.stringify({version:process.versions.node,arch:process.arch,execPath:process.execPath}))" 2>$null | ConvertFrom-Json
        $Version = [Version][string]$Probe.version
        if ($Version -lt [Version]'20.9.0' -or [string]$Probe.arch -ne 'x64') { continue }
        $Result = [ordered]@{
            schema_version = 1
            path = [IO.Path]::GetFullPath([string]$Probe.execPath)
            version = $Version.ToString()
            architecture = [string]$Probe.arch
            portable = $true
        }
        if ($Output -eq 'Json') { $Result | ConvertTo-Json -Compress } else { [string]$Result.path }
        exit 0
    } catch {}
}

Write-Error 'Aucun runtime Node.js x64 compatible (>= 20.9) n a ete trouve.'
exit 2
