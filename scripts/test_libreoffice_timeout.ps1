Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Errors = $null
$Ast = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot 'manage-libreoffice.ps1'), [ref]$null, [ref]$Errors)
if ($Errors.Count) { throw 'Syntaxe LibreOffice invalide.' }
$Function = $Ast.Find({ param($Node)
    $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $Node.Name -eq 'Wait-LibreOfficeOperation'
}, $true)
if (-not $Function) { throw 'Fonction de timeout absente.' }
. ([scriptblock]::Create($Function.Extent.Text))
$OperationTimeoutSeconds = 1
$Process = Start-Process powershell.exe -ArgumentList '-NoProfile','-Command','Start-Sleep -Seconds 30' -WindowStyle Hidden -PassThru
$Rejected = $false
try { Wait-LibreOfficeOperation $Process }
catch {
    if ($_.Exception.Message -notlike '*non confirmee*') { throw }
    $Rejected = $true
}
if (-not $Rejected) { throw 'Le timeout ne rejette pas une operation bloquee.' }
if (-not $Process.WaitForExit(5000)) { throw 'Le processus bloque survit au timeout.' }
$Process.Dispose()
$Process = Start-Process powershell.exe -ArgumentList '-NoProfile','-Command','exit 0' -WindowStyle Hidden -PassThru
$OperationTimeoutSeconds = 10
try {
    Wait-LibreOfficeOperation $Process
    if ($Process.ExitCode -ne 0) { throw 'Le chemin nominal est invalide.' }
} finally { $Process.Dispose() }
Write-Output 'LibreOffice timeout OK - succes et interruption bornee.'
