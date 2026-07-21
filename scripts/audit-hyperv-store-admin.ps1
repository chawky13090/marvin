param(
    [string]$ResultPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'data\hyperv-store-audit.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Audit administrateur requis.'
}

Import-Module Hyper-V -ErrorAction Stop
$vmErrors = @()
$vms = @(Get-VM -ErrorAction SilentlyContinue -ErrorVariable +vmErrors | ForEach-Object {
    [ordered]@{ name = $_.Name; id = [string]$_.Id; path = $_.Path; state = [string]$_.State }
})
$store = 'C:\ProgramData\Microsoft\Windows\Hyper-V'
$items = @(Get-ChildItem -LiteralPath $store -Force -Recurse -Depth 3 -ErrorAction SilentlyContinue | ForEach-Object {
    [ordered]@{
        path = $_.FullName
        container = $_.PSIsContainer
        extension = $_.Extension
        link_type = [string]$_.LinkType
        target = @($_.Target)
        length = $(if ($_.PSIsContainer) { $null } else { $_.Length })
        attributes = [string]$_.Attributes
    }
})
$result = [ordered]@{
    timestamp = (Get-Date).ToString('o')
    elevated = $true
    vms = $vms
    vm_errors = @($vmErrors | ForEach-Object { $_.Exception.Message })
    store = $store
    items = $items
}
$parent = Split-Path $ResultPath -Parent
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$temporary = $ResultPath + '.tmp'
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporary -Encoding UTF8
Move-Item -LiteralPath $temporary -Destination $ResultPath -Force
