[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$candidates = @(
    (Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\Ollama\ollama.exe')
)

$pathCommand = Get-Command ollama.exe -ErrorAction SilentlyContinue
if ($null -ne $pathCommand -and $pathCommand.Source) {
    $candidates += $pathCommand.Source
}

foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        Write-Output (Resolve-Path -LiteralPath $candidate).Path
        exit 0
    }
}

Write-Error 'Executable Ollama introuvable.'
exit 1
