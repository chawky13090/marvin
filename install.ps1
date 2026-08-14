[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$Installer = Join-Path $ProjectRoot 'INSTALLER-MARVIN.bat'
if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    throw "Installateur canonique introuvable : $Installer"
}

Write-Host 'Ouverture de l installateur Windows en un clic de Marvin...' -ForegroundColor Cyan
$Process = Start-Process -FilePath $env:ComSpec `
    -ArgumentList @('/d', '/c', 'call', "`"$Installer`"") `
    -WorkingDirectory $ProjectRoot -Wait -PassThru
exit [int]$Process.ExitCode
