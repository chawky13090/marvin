[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9._-]{1,64}$')]
    [string]$TargetUser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Cette operation exige une elevation administrateur.'
}

$User = Get-LocalUser -Name $TargetUser -ErrorAction Stop
$Group = Get-LocalGroup -Name 'docker-users' -ErrorAction Stop
$AlreadyMember = Get-LocalGroupMember -Group $Group -ErrorAction Stop |
    Where-Object { $_.SID -eq $User.SID } |
    Select-Object -First 1
if ($AlreadyMember) {
    Write-Output "Acces Docker deja accorde a $TargetUser."
    exit 0
}

if ($PSCmdlet.ShouldProcess($TargetUser, 'Ajouter au groupe local docker-users')) {
    Add-LocalGroupMember -Group $Group -Member $User -ErrorAction Stop
}

$Verified = Get-LocalGroupMember -Group $Group -ErrorAction Stop |
    Where-Object { $_.SID -eq $User.SID } |
    Select-Object -First 1
if (-not $Verified) { throw "L appartenance de $TargetUser au groupe docker-users n a pas ete confirmee." }
Write-Output "Acces Docker accorde a $TargetUser. Une nouvelle session Windows est requise."
