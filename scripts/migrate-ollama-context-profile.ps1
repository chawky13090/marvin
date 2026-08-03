[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [ValidateSet('Inspect', 'Apply')]
    [string]$Action = 'Inspect',

    [switch]$NoConfirm
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($NoConfirm) {
    $ConfirmPreference = 'None'
}

$LegacyValue = '32768'
$Current = [Environment]::GetEnvironmentVariable('OLLAMA_CONTEXT_LENGTH', 'User')
$Result = [ordered]@{
    schema = 'marvin.ollama-context-environment-migration/1.0'
    action = $Action
    previous_value = $Current
    changed = $false
    status = 'not_required'
}

if ($Current -eq $LegacyValue) {
    $Result.status = 'legacy_fixed_value_detected'
    if ($Action -eq 'Apply' -and $PSCmdlet.ShouldProcess(
        'Variable utilisateur OLLAMA_CONTEXT_LENGTH',
        'Retirer la valeur fixe historique 32768'
    )) {
        [Environment]::SetEnvironmentVariable('OLLAMA_CONTEXT_LENGTH', $null, 'User')
        $Result.changed = $true
        $Result.status = 'legacy_fixed_value_removed'
    }
} elseif ($Current) {
    $Result.status = 'custom_user_value_preserved'
}

$Result | ConvertTo-Json -Compress
