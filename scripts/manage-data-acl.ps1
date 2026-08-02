[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [ValidateSet('Audit', 'Apply', 'Restore')]
    [string]$Action = 'Audit',
    [string]$DataRoot,
    [string]$RuntimeRoot,
    [string]$BackupPath,
    [switch]$NoConfirm
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($NoConfirm) { $ConfirmPreference = 'None' }

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $DataRoot) { $DataRoot = Join-Path $ProjectRoot 'data' }
if (-not $RuntimeRoot) { $RuntimeRoot = Join-Path $ProjectRoot 'runtime\security' }
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
$RuntimeRoot = [System.IO.Path]::GetFullPath($RuntimeRoot)
$ResultPath = Join-Path $RuntimeRoot 'data-acl-result.json'
$CurrentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$CurrentSid = $CurrentIdentity.User.Value
$AllowedSids = @($CurrentSid, 'S-1-5-18', 'S-1-5-32-544')

function Invoke-Icacls {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $global:LASTEXITCODE = 0
    & icacls.exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "icacls a échoué avec le code $LASTEXITCODE."
    }
}

function Convert-IdentityToSid {
    param([System.Security.Principal.IdentityReference]$Identity)
    try {
        return $Identity.Translate([System.Security.Principal.SecurityIdentifier]).Value
    } catch {
        return $Identity.Value
    }
}

function Get-AclStatus {
    if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) {
        throw 'Le dossier data est absent.'
    }
    $RootAcl = Get-Acl -LiteralPath $DataRoot
    $Unsafe = @()
    foreach ($Rule in $RootAcl.Access) {
        if ($Rule.AccessControlType -ne 'Allow') { continue }
        $Sid = Convert-IdentityToSid $Rule.IdentityReference
        if ($Sid -notin $AllowedSids) { $Unsafe += $Sid }
    }
    $Sensitive = @(
        (Join-Path $DataRoot 'secretary.db'),
        (Join-Path $DataRoot 'windows_secrets.dpapi.json'),
        (Join-Path $DataRoot 'backups'),
        (Join-Path $DataRoot 'maintenance')
    )
    $ExplicitUnsafe = @()
    $ExplicitUnsafePaths = @()
    foreach ($Item in Get-ChildItem -LiteralPath $DataRoot -Force -Recurse) {
        $Path = $Item.FullName
        $Acl = Get-Acl -LiteralPath $Path
        foreach ($Rule in $Acl.Access) {
            if ($Rule.AccessControlType -ne 'Allow' -or $Rule.IsInherited) { continue }
            $Sid = Convert-IdentityToSid $Rule.IdentityReference
            if ($Sid -notin $AllowedSids) {
                $ExplicitUnsafe += $Sid
                $ExplicitUnsafePaths += $Path
            }
        }
    }
    $Compliant = $RootAcl.AreAccessRulesProtected -and $Unsafe.Count -eq 0 -and $ExplicitUnsafe.Count -eq 0
    return [ordered]@{
        compliant = $Compliant
        owner = $RootAcl.Owner
        inheritance_protected = $RootAcl.AreAccessRulesProtected
        allowed_sids = $AllowedSids
        unsafe_root_grants = @($Unsafe | Sort-Object -Unique)
        unsafe_explicit_child_grants = @($ExplicitUnsafe | Sort-Object -Unique)
        unsafe_explicit_child_paths = @($ExplicitUnsafePaths | Sort-Object -Unique)
        sensitive_paths_checked = @($Sensitive | Where-Object { Test-Path -LiteralPath $_ }).Count
    }
}

function Get-ExplicitChildAclPaths {
    $Paths = @()
    foreach ($Item in Get-ChildItem -LiteralPath $DataRoot -Force -Recurse) {
        $Acl = Get-Acl -LiteralPath $Item.FullName
        if (@($Acl.Access | Where-Object { -not $_.IsInherited }).Count -gt 0) {
            $Paths += $Item.FullName
        }
    }
    return $Paths
}

function Write-Result {
    param([hashtable]$Payload)
    New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
    $Payload.generated_at = [DateTimeOffset]::UtcNow.ToString('o')
    $Json = $Payload | ConvertTo-Json -Depth 6 -Compress
    $Temporary = "$ResultPath.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        [System.IO.File]::WriteAllText($Temporary, $Json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $Temporary -Destination $ResultPath -Force
    } finally {
        Remove-Item -LiteralPath $Temporary -Force -ErrorAction SilentlyContinue
    }
    Write-Output $Json
}

if ($env:OS -ne 'Windows_NT') { throw 'La gestion ACL Marvin requiert Windows.' }

if ($Action -eq 'Audit') {
    Write-Result ([ordered]@{ success = $true; action = 'audit'; status = Get-AclStatus })
    exit 0
}

if ($Action -eq 'Restore') {
    if (-not $BackupPath) { throw 'BackupPath est requis pour Restore.' }
    $ResolvedBackup = [System.IO.Path]::GetFullPath($BackupPath)
    $RuntimePrefix = $RuntimeRoot.TrimEnd('\') + '\'
    if (-not $ResolvedBackup.StartsWith($RuntimePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'La sauvegarde ACL doit rester sous runtime\security.'
    }
    if (-not (Test-Path -LiteralPath $ResolvedBackup -PathType Leaf)) {
        throw 'La sauvegarde ACL est introuvable.'
    }
    $MetadataPath = "$ResolvedBackup.json"
    if (-not (Test-Path -LiteralPath $MetadataPath -PathType Leaf)) {
        throw 'Les métadonnées de rollback ACL sont introuvables.'
    }
    $Metadata = Get-Content -Raw -LiteralPath $MetadataPath | ConvertFrom-Json
    $BackupSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ResolvedBackup).Hash.ToLowerInvariant()
    if ($BackupSha256 -ne [string]$Metadata.backup_sha256) {
        throw 'L empreinte de la sauvegarde ACL ne correspond pas aux metadonnees.'
    }
    $ParentAcl = Get-Acl -LiteralPath (Split-Path -Parent $DataRoot)
    $ParentSddl = $ParentAcl.GetSecurityDescriptorSddlForm(
        [System.Security.AccessControl.AccessControlSections]::Access
    )
    if ($ParentSddl -ne [string]$Metadata.parent_access_sddl) {
        throw 'Le parent du dossier data a changé; rollback automatique refusé.'
    }
    if ([bool]$Metadata.root_was_protected) {
        throw 'Ce snapshot exige une restauration ACL élevée non prise en charge automatiquement.'
    }
    if ($PSCmdlet.ShouldProcess($DataRoot, 'Restaurer les ACL sauvegardées')) {
        Invoke-Icacls @($DataRoot, '/inheritance:e', '/Q')
        foreach ($Child in Get-ChildItem -LiteralPath $DataRoot -Force) {
            Invoke-Icacls @($Child.FullName, '/reset', '/T', '/C', '/Q')
        }
    }
    Write-Result ([ordered]@{
        success = $true
        action = 'restore'
        backup_path = $ResolvedBackup
        backup_sha256 = $BackupSha256
        metadata_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $MetadataPath).Hash.ToLowerInvariant()
        status = Get-AclStatus
    })
    exit 0
}

if (@(Get-ChildItem -LiteralPath $DataRoot -Force -Recurse -Attributes ReparsePoint -ErrorAction Stop).Count -gt 0) {
    throw 'Les points de réanalyse sont interdits pendant le durcissement ACL.'
}
$InitialStatus = Get-AclStatus
if ($InitialStatus.compliant) {
    Write-Result ([ordered]@{ success = $true; action = 'apply'; already_compliant = $true; status = $InitialStatus })
    exit 0
}
if ($InitialStatus.inheritance_protected) {
    throw 'Une ACL racine explicite non conforme exige une intervention élevée manuelle.'
}
$ExplicitChildPaths = @(Get-ExplicitChildAclPaths)
if ($ExplicitChildPaths.Count -gt 0) {
    throw 'Des ACL enfants explicites empêchent un rollback non élevé exact.'
}
New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
if (-not $BackupPath) {
    $Stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $BackupPath = Join-Path $RuntimeRoot "data-acl-$Stamp.txt"
}
$BackupPath = [System.IO.Path]::GetFullPath($BackupPath)
$RuntimePrefix = $RuntimeRoot.TrimEnd('\') + '\'
if (-not $BackupPath.StartsWith($RuntimePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'La sauvegarde ACL doit rester sous runtime\security.'
}

if ($PSCmdlet.ShouldProcess($DataRoot, 'Sauvegarder puis durcir récursivement les ACL')) {
    Invoke-Icacls @($DataRoot, '/save', $BackupPath, '/T', '/C', '/Q')
    $BackupSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $BackupPath).Hash.ToLowerInvariant()
    $ParentAcl = Get-Acl -LiteralPath (Split-Path -Parent $DataRoot)
    $Metadata = [ordered]@{
        schema_version = 1
        data_root = $DataRoot
        root_was_protected = $InitialStatus.inheritance_protected
        backup_sha256 = $BackupSha256
        parent_access_sddl = $ParentAcl.GetSecurityDescriptorSddlForm(
            [System.Security.AccessControl.AccessControlSections]::Access
        )
    }
    [System.IO.File]::WriteAllText(
        "$BackupPath.json",
        (($Metadata | ConvertTo-Json -Compress) + [Environment]::NewLine),
        [System.Text.UTF8Encoding]::new($false)
    )
    try {
        Invoke-Icacls @(
            $DataRoot,
            '/inheritance:r',
            '/grant:r', "*$CurrentSid`:(OI)(CI)(F)",
            '/grant:r', '*S-1-5-18:(OI)(CI)(F)',
            '/grant:r', '*S-1-5-32-544:(OI)(CI)(F)',
            '/Q'
        )
        foreach ($Child in Get-ChildItem -LiteralPath $DataRoot -Force) {
            Invoke-Icacls @($Child.FullName, '/reset', '/T', '/C', '/Q')
        }
        $Status = Get-AclStatus
        if (-not $Status.compliant) { throw 'Le contrôle ACL final n’est pas conforme.' }
    } catch {
        Invoke-Icacls @($DataRoot, '/inheritance:e', '/Q')
        foreach ($Child in Get-ChildItem -LiteralPath $DataRoot -Force) {
            Invoke-Icacls @($Child.FullName, '/reset', '/T', '/C', '/Q')
        }
        throw
    }
}

Write-Result ([ordered]@{
    success = $true
    action = 'apply'
    backup_path = $BackupPath
    backup_sha256 = $BackupSha256
    metadata_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath "$BackupPath.json").Hash.ToLowerInvariant()
    status = Get-AclStatus
})
