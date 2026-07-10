# launch_elevated_daemon.ps1 — Lance le démon élevé de Marvin (pattern sidecar).
# Affiche UNE invite UAC (élévation standard Windows, transparente pour l'utilisateur).
# Le backend principal de Marvin continue de tourner en utilisateur NORMAL ; seul ce
# petit démon tourne en administrateur, et n'accepte qu'une allowlist stricte d'actions
# via canal IPC local authentifié (voir elevated_daemon.py).

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $here '.venv\Scripts\python.exe'
$daemonScript = Join-Path $here 'elevated_daemon.py'

if (-not (Test-Path $venvPython)) {
    Write-Error "Python introuvable : $venvPython (l'environnement virtuel backend est-il installé ?)"
    exit 1
}

Write-Host "Lancement du démon élevé de Marvin (une invite d'élévation Windows va s'afficher)..." -ForegroundColor Cyan
Start-Process -FilePath $venvPython -ArgumentList "`"$daemonScript`"" -WorkingDirectory $here -Verb RunAs
