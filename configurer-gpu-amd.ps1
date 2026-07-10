# ============================================================================
#  Marvin / SecretaryAI — Activer le GPU AMD (Radeon) pour Ollama
#  Détecte la carte AMD, applique le bon HSA_OVERRIDE_GFX_VERSION (ROCm),
#  puis redémarre Ollama. Couvre un maximum de modèles AMD.
#  Lancer :  powershell -ExecutionPolicy Bypass -File configurer-gpu-amd.ps1
# ============================================================================
$ErrorActionPreference = "SilentlyContinue"
Write-Host ""
Write-Host "==== Configuration GPU AMD pour Ollama ====" -ForegroundColor Cyan
Write-Host ""

# --- 1. Détecter la carte AMD ---
$cards = @()
Get-ChildItem 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}' | ForEach-Object {
    $p = Get-ItemProperty $_.PSPath
    if ($p.DriverDesc) { $cards += $p.DriverDesc }
}
if (-not $cards) { $cards = (Get-CimInstance Win32_VideoController).Name }

$amd = $cards | Where-Object { $_ -match 'AMD|Radeon|RX |Vega|ATI|FirePro|Instinct' } | Select-Object -First 1
if (-not $amd) {
    Write-Host "[X] Aucune carte AMD detectee. Cartes vues : $($cards -join ', ')" -ForegroundColor Yellow
    Write-Host "    (Si tu as un GPU AMD, mets a jour ses pilotes puis relance.)"
    Read-Host "Appuyez sur Entree pour quitter"
    exit
}
Write-Host "[OK] Carte AMD detectee : $amd" -ForegroundColor Green
Write-Host ""

# --- 2. Déterminer le HSA_OVERRIDE_GFX_VERSION adapté ---
#     (valeur = architecture ROCm supportee la plus proche)
$gfx = $null; $needFork = $false; $arch = ""
#   Ordre important : les RX 5x00 (RDNA1, 4 chiffres) AVANT les RX 5xx (Polaris, 3 chiffres).
switch -Regex ($amd) {
    '7900|7800|7700|7600|780M|760M|Radeon 8\d{2}M|RX 7\d{3}' { $gfx = "11.0.0"; $arch = "RDNA3"; break }
    '6900|6950|6800'                                         { $gfx = "10.3.0"; $arch = "RDNA2 (gfx1030, natif)"; break }
    '6750|6700|6650|6600|6500|6400|680M|660M|RX 6\d{3}'      { $gfx = "10.3.0"; $arch = "RDNA2"; break }
    '5700|5600|5500|5300|RX 5\d{3}'                          { $gfx = "10.1.0"; $arch = "RDNA1"; $needFork = $true; break }
    'Radeon VII'                                             { $gfx = "9.0.6";  $arch = "Vega20"; break }
    'Vega'                                                   { $gfx = "9.0.0";  $arch = "Vega"; $needFork = $true; break }
    'RX [45]\d{2}|Polaris'                                   { $gfx = "8.0.3";  $arch = "Polaris"; $needFork = $true; break }
    default                                                  { $gfx = "10.3.0"; $arch = "inconnu (essai)"; $needFork = $true }
}
Write-Host "Architecture estimee : $arch  ->  HSA_OVERRIDE_GFX_VERSION = $gfx"
Write-Host ""

# --- 3. Appliquer la variable d'environnement (persistante, niveau utilisateur) ---
setx HSA_OVERRIDE_GFX_VERSION $gfx | Out-Null
$env:HSA_OVERRIDE_GFX_VERSION = $gfx
Write-Host "[OK] Variable HSA_OVERRIDE_GFX_VERSION = $gfx enregistree." -ForegroundColor Green
Write-Host ""

# --- 4. Redémarrer Ollama pour qu'il prenne la variable en compte ---
Write-Host "Redemarrage d'Ollama..."
Get-Process ollama -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
$ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $ollamaExe) { $ollamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 3
Write-Host "[OK] Ollama redemarre avec le GPU AMD active." -ForegroundColor Green
Write-Host ""

# --- 5. Conseils / vérification ---
Write-Host "==== Etapes suivantes ====" -ForegroundColor Cyan
if ($needFork) {
    Write-Host "[!] Ta carte ($arch) n'est PAS officiellement supportee par Ollama standard." -ForegroundColor Yellow
    Write-Host "    Si le GPU n'est toujours pas utilise, installe la version communautaire" -ForegroundColor Yellow
    Write-Host "    qui couvre BEAUCOUP plus de cartes AMD :" -ForegroundColor Yellow
    Write-Host "      https://github.com/likelovewant/ollama-for-amd/releases" -ForegroundColor White
    Write-Host "    (puis relance ce script pour reappliquer HSA_OVERRIDE_GFX_VERSION)."
    Write-Host ""
}
Write-Host "Pour VERIFIER que le GPU est utilise :"
Write-Host "  1) Pose une question dans Marvin (le modele se charge)"
Write-Host "  2) Dans un terminal :  ollama ps"
Write-Host "     -> colonne PROCESSOR : '100% GPU' = parfait, '100% CPU' = GPU pas utilise."
Write-Host ""
Write-Host "[INFO] Si ca instabilise le PC, annule avec :  setx HSA_OVERRIDE_GFX_VERSION """""
Write-Host ""
Read-Host "Appuyez sur Entree pour terminer"
