[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$AnswerFile,
    [Parameter(Mandatory)]
    [string]$OutputIso
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Runtime Python Marvin absent pour construire le media Autounattend.'
}
$answer = (Resolve-Path -LiteralPath $AnswerFile).Path
$output = [IO.Path]::GetFullPath($OutputIso)
& $python (Join-Path $PSScriptRoot 'build_unattend_iso.py') --answer $answer --output $output
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $output -PathType Leaf)) {
    throw 'La construction verifiee du media Autounattend a echoue.'
}
& icacls.exe $output /grant:r "${env:USERNAME}:F" '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
