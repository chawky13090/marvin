Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$setup = Join-Path $PSScriptRoot 'prepare-windows-test-forge.ps1'
$log = Join-Path $root '_windows_sandbox_setup.log'

try {
    & $setup -EnableSandbox -Confirm:$false 2>&1 |
        Tee-Object -FilePath $log
    exit $LASTEXITCODE
}
catch {
    $_ | Format-List * -Force | Out-String |
        Set-Content -LiteralPath $log -Encoding UTF8
    exit 1
}
