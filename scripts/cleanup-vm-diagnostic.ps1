Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$path = 'C:\Users\Chawb\secretary-ai\data\.windows-autologon-diagnostic-secret.txt'
if ((Test-Path -LiteralPath $path) -and ([IO.Path]::GetFullPath($path) -eq $path)) {
    Remove-Item -LiteralPath $path -Force
}
