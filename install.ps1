[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Façade de compatibilité. Toute l'installation reste définie dans un seul
# orchestrateur afin d'éviter deux procédures divergentes.
$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$installer = Join-Path $projectRoot 'INSTALLER-NOUVEAU-PC.bat'
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Installateur canonique introuvable : $installer"
}

Write-Host 'Ouverture de l installateur Windows canonique de Marvin...' -ForegroundColor Cyan
$process = Start-Process `
    -FilePath $env:ComSpec `
    -ArgumentList @('/d', '/c', 'call', "`"$installer`"") `
    -WorkingDirectory $projectRoot `
    -Wait `
    -PassThru
exit [int]$process.ExitCode
