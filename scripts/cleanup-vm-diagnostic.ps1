[CmdletBinding(SupportsShouldProcess)]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$dataRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'data'))
$path = [IO.Path]::GetFullPath((Join-Path $dataRoot '.windows-autologon-diagnostic-secret.txt'))
$dataPrefix = $dataRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $path.StartsWith($dataPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Le fichier de diagnostic résolu sort du dossier data de Marvin.'
}
if ((Test-Path -LiteralPath $path -PathType Leaf) -and $PSCmdlet.ShouldProcess($path, 'Supprimer le secret de diagnostic temporaire')) {
    Remove-Item -LiteralPath $path -Force
}
