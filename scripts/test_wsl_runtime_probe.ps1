Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$Errors=$null;$Tokens=$null
$Ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'enable-docker-wsl-prerequisites.ps1'),[ref]$Tokens,[ref]$Errors)
if($Errors.Count){throw 'Syntaxe prerequis WSL invalide.'}
$Definition=$Ast.Find({param($Node) $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq 'Test-WslVersionResult'},$true)
if(-not $Definition){throw 'Probe WSL absent.'}
. ([scriptblock]::Create($Definition.Extent.Text))
foreach($Case in @(
    @{exit_code=0;output='';expected=$false},
    @{exit_code=0;output='Run wsl --install to install WSL';expected=$false},
    @{exit_code=0;output='Usage: wsl.exe version 10.0.26200';expected=$false},
    @{exit_code=0;output='WSL version: 1.0.0.0';expected=$false},
    @{exit_code=0;output='WSLg version: 3.0.1.0';expected=$false},
    @{exit_code=1;output='WSL version: 3.0.1.0';expected=$false},
    @{exit_code=0;output='WSL version: 3.0.1.0';expected=$true},
    @{exit_code=0;output='Version WSL : 2.6.3.0';expected=$true}
)){
    if((Test-WslVersionResult $Case) -ne $Case.expected){throw 'Decision WSL incorrecte.'}
}
Write-Output 'WSL runtime probe OK - aide, vide et ancienne version refuses; versions reelles acceptees.'
$DockerAst=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'ensure-docker-desktop.ps1'),[ref]$Tokens,[ref]$Errors)
$Definition=$DockerAst.Find({param($Node) $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq 'Test-DockerPrivilegedAccessRequired'},$true)
. ([scriptblock]::Create($Definition.Extent.Text))
if(Test-DockerPrivilegedAccessRequired 'wsl-2'){throw 'WSL exige un groupe privilegie inutile.'}
if(-not(Test-DockerPrivilegedAccessRequired 'hyper-v')){throw 'Autorisation Hyper-V absente.'}
$UninstallAst=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'uninstall-marvin.ps1'),[ref]$Tokens,[ref]$Errors)
if($Errors.Count){throw 'Syntaxe desinstallation invalide.'}
$Definition=$UninstallAst.Find({param($Node) $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq 'Test-UninstallContainerOwnership'},$true)
. ([scriptblock]::Create($Definition.Extent.Text))
if(-not(Test-UninstallContainerOwnership @(@{Type='bind';Source='C:\Marvin\docker\settings.yml'}) 'C:\Marvin')){throw 'Montage propre refuse.'}
if(Test-UninstallContainerOwnership @(@{Type='bind';Source='C:\Marvin-other\settings.yml'}) 'C:\Marvin'){throw 'Montage voisin accepte.'}
if(Test-UninstallContainerOwnership @(@{Type='volume';Source='C:\Marvin'}) 'C:\Marvin'){throw 'Volume partage accepte.'}
$Definition=$UninstallAst.Find({param($Node) $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq 'Read-UninstallContainerInspection'},$true)
. ([scriptblock]::Create($Definition.Extent.Text))
$Id=('a'*64)
$Parsed=Read-UninstallContainerInspection ($Id+'|[{"Type":"bind","Source":"C:\\Marvin\\settings.yml"}]')
if($Parsed.id -ne $Id -or -not(Test-UninstallContainerOwnership $Parsed.mounts 'C:\Marvin')){throw 'Inspection propre mal parse.'}
$Rejected=$false
try{Read-UninstallContainerInspection 'not-an-id|[]'|Out-Null}catch{$Rejected=$true}
if(-not$Rejected){throw 'Identite invalide acceptee.'}
Write-Output 'Docker policy OK - privileges par backend et ownership des montages.'
