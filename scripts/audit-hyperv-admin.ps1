[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$resultPath = Join-Path $root 'data\hyperv-admin-audit.json'
$result = [ordered]@{
    timestamp = [DateTimeOffset]::Now.ToString('o')
    elevated = $false
    vmms = $null
    vm_host = $null
    vms = @()
    error = $null
}

try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    $result.elevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $result.vmms = [string](Get-Service vmms -ErrorAction Stop).Status
    $hostConfig = Get-VMHost -ErrorAction Stop
    $result.vm_host = [ordered]@{
        name = $hostConfig.Name
        virtual_machine_path = $hostConfig.VirtualMachinePath
        virtual_hard_disk_path = $hostConfig.VirtualHardDiskPath
    }
    $result.vms = @(Get-VM -ErrorAction Stop | ForEach-Object {
        [ordered]@{
            name = $_.Name
            id = [string]$_.Id
            state = [string]$_.State
            generation = $_.Generation
            checkpoint_type = [string]$_.CheckpointType
            checkpoints = @((Get-VMCheckpoint -VMName $_.Name -ErrorAction SilentlyContinue).Name)
        }
    })
}
catch {
    $result.error = $_.Exception.Message
}

New-Item -ItemType Directory -Path (Split-Path -Parent $resultPath) -Force | Out-Null
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $resultPath -Encoding UTF8
$result | ConvertTo-Json -Depth 8
if ($result.error) { exit 1 }
