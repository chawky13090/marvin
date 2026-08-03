[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$PythonPath,

    [string]$OutputBatch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Resolver = Join-Path $PSScriptRoot 'resolve-ollama-context-profile.py'
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Runtime Python Marvin introuvable."
}
if (-not (Test-Path -LiteralPath $Resolver -PathType Leaf)) {
    throw "Resolveur de contexte Ollama introuvable."
}

# Le resolveur peut retourner 2 pour un profil bootstrap tout en produisant un
# environnement sûr. PowerShell relaie les lignes et ne transforme pas ce repli
# explicite en absence de configuration pour le batch appelant.
$Lines = @(& $PythonPath $Resolver --format cmd)
if ($LASTEXITCODE -notin @(0, 2)) {
    throw "Le resolveur de contexte Ollama a échoué ($LASTEXITCODE)."
}
if ($OutputBatch) {
    $ResolvedOutput = [System.IO.Path]::GetFullPath($OutputBatch)
    $AllowedRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if (-not $ResolvedOutput.StartsWith($AllowedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Le fichier batch temporaire doit rester dans TEMP."
    }
    $BatchLines = foreach ($Line in $Lines) {
        if ($Line -notmatch '^(OLLAMA_CONTEXT_LENGTH|OLLAMA_KV_CACHE_TYPE|OLLAMA_FLASH_ATTENTION|OLLAMA_NUM_PARALLEL|MARVIN_OLLAMA_PROFILE_STATUS)=([A-Za-z0-9_.-]+)$') {
            throw "Sortie de profil Ollama invalide."
        }
        'set "{0}"' -f $Line
    }
    [System.IO.File]::WriteAllLines($ResolvedOutput, $BatchLines, [System.Text.Encoding]::ASCII)
} else {
    $Lines
}
exit 0
