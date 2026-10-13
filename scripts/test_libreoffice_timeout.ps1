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

foreach ($Name in @('Get-PinnedOfficeInstaller','Invoke-PinnedOfficeInstaller','Invoke-DirectOfficeRemoval')) {
    $Definition = $Ast.Find({param($Node) $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq $Name}, $true)
    if (-not $Definition) { throw "Fonction absente : $Name" }
    . ([scriptblock]::Create($Definition.Extent.Text))
}
$ProjectRoot = Join-Path ([IO.Path]::GetTempPath()) ('marvin-office-test-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $ProjectRoot 'runtime\install\downloads') -Force | Out-Null
try {
    $File = Join-Path $ProjectRoot 'runtime\install\downloads\fixture.msi'
    [IO.File]::WriteAllText($File, 'fixture')
    $Digest = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash.ToLowerInvariant()
    $Component = @{file='fixture.msi';url='https://downloadarchive.documentfoundation.org/fixture.msi';sha256=$Digest}
    if ((Get-PinnedOfficeInstaller $Component) -ne $File) { throw 'Cache verifie non reutilise.' }
    $Bad = @{file='../escape.msi';url=$Component.url;sha256=$Digest}
    $Rejected=$false
    try { Get-PinnedOfficeInstaller $Bad | Out-Null } catch { $Rejected=$true }
    if (-not $Rejected) { throw 'Traversal accepte.' }
    $Bad = @{file='fixture.msi';url='https://example.com/fixture.msi';sha256=$Digest}
    $Rejected=$false
    try { Get-PinnedOfficeInstaller $Bad | Out-Null } catch { $Rejected=$true }
    if (-not $Rejected) { throw 'Origine non autorisee acceptee.' }
    function Save-OfficeDownload { param($Uri,$Path) [IO.File]::WriteAllText($Path,'corrupted') }
    [IO.File]::WriteAllText($File, 'corrupted-cache')
    $Rejected=$false
    try { Get-PinnedOfficeInstaller $Component | Out-Null } catch { if($_.Exception.Message -notlike '*SHA-256*'){throw};$Rejected=$true }
    if (-not $Rejected) { throw 'Telechargement corrompu accepte.' }
    if (@(Get-ChildItem (Split-Path $File) -Filter '*.partial').Count -ne 0) { throw 'Partiel non nettoye.' }
    [IO.File]::WriteAllText($File, 'fixture')
    function Start-Process {
        param($FilePath,$ArgumentList,[switch]$PassThru,$Verb)
        $script:ObservedArguments=$ArgumentList
        $Fake=[pscustomobject]@{ExitCode=3010;Handle=1}
        $Fake|Add-Member ScriptMethod WaitForExit {param($Timeout) return $true}
        $Fake|Add-Member ScriptMethod Dispose {}
        return $Fake
    }
    if ((Invoke-PinnedOfficeInstaller $File $Component -Msi) -ne 3010) { throw 'Reboot requis non propage.' }
    if ($script:ObservedArguments -notcontains '/norestart') { throw 'Redemarrage automatique non interdit.' }
    if ((Invoke-DirectOfficeRemoval '{3B467719-C25B-478C-8F4C-8E2EDA0E2093}') -ne 3010) { throw 'Reboot desinstallation perdu.' }
    if ($script:ObservedArguments -notcontains '/x') { throw 'Desinstallation directe incorrecte.' }
    $Rejected=$false
    try { Invoke-DirectOfficeRemoval 'arbitrary arguments' | Out-Null } catch { $Rejected=$true }
    if (-not $Rejected) { throw 'ProductCode arbitraire accepte.' }
    [IO.File]::WriteAllText($File, 'changed-after-download')
    $Rejected=$false
    try { Invoke-PinnedOfficeInstaller $File $Component -Msi | Out-Null } catch { $Rejected=$true }
    if (-not $Rejected) { throw 'Mutation avant lancement non refusee.' }
    $Installer=Get-Content (Join-Path $PSScriptRoot 'install-marvin-oneclick.ps1') -Raw
    if ($Installer -notmatch "(?s)libreoffice_required.*?LASTEXITCODE -eq 3010.*?Register-InstallResumeAfterRestart") { throw 'Reprise Office absente.' }
} finally {
    $Resolved=[IO.Path]::GetFullPath($ProjectRoot)
    if ($Resolved.StartsWith([IO.Path]::GetTempPath(),[StringComparison]::OrdinalIgnoreCase) -and (Split-Path $Resolved -Leaf) -like 'marvin-office-test-*') {
        Remove-Item -LiteralPath $Resolved -Recurse -Force
    }
}
Write-Output 'LibreOffice direct OK - cache, SHA, origines, traversal, mutation et propagation 3010.'
