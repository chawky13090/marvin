[CmdletBinding(SupportsShouldProcess = $true)]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Launcher = Join-Path $ProjectRoot 'LANCER-AVATAR-MARVIN.bat'
$Electron = Join-Path $ProjectRoot 'node_modules\electron\dist\electron.exe'
$Icon = Join-Path $ProjectRoot 'public\marvin-avatar.ico'
$Desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
$ShortcutPath = Join-Path $Desktop 'Marvin Avatar.lnk'

if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) {
    throw "Lanceur avatar introuvable : $Launcher"
}
if (-not (Test-Path -LiteralPath $Electron -PathType Leaf)) {
    throw "Runtime Electron absent : exécutez d'abord npm install puis node node_modules\electron\install.js."
}

if ($PSCmdlet.ShouldProcess($ShortcutPath, 'Créer le raccourci de bureau Marvin Avatar')) {
    $Shell = New-Object -ComObject WScript.Shell
    try {
        $Shortcut = $Shell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = $Launcher
        $Shortcut.WorkingDirectory = $ProjectRoot
        $Shortcut.IconLocation = if (Test-Path -LiteralPath $Icon -PathType Leaf) { "$Icon,0" } else { "$Electron,0" }
        $Shortcut.Description = 'Parler à Marvin et contrôler son démarrage'
        $Shortcut.Save()
    }
    finally {
        if ($null -ne $Shell) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($Shell) }
    }
}

[pscustomobject]@{ success = (Test-Path -LiteralPath $ShortcutPath); shortcut = $ShortcutPath } | ConvertTo-Json -Compress
