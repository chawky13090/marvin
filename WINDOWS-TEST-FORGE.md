# Test Forge Windows et Linux

Cible technique : Windows Pro avec Hyper-V ; Docker Desktop en mode conteneurs Linux  
Versions : Windows build 26200 observé ; Docker Engine 29.6.1 ; PowerShell 5.1+  
Niveau requis : N3  
Impact de production : Faible, puis redémarrage requis lors de l'activation de Windows Sandbox  
Privilèges requis : Administrateur uniquement pour activer la fonctionnalité Windows  
Durée indicative : 10 à 20 minutes hors redémarrage  
Sauvegarde préalable : non requise ; aucun fichier utilisateur n'est modifié  
Plan de rollback : désactiver `Containers-DisposableClientVM`

## Architecture retenue

### Linux

1. Syntaxe et analyse statique dans un conteneur sans réseau, racine en lecture seule,
   capacités supprimées et ressources bornées.
2. Pour un livrable nécessitant des dépendances, second conteneur Debian 13 jetable avec
   Internet, sans secret hôte, socket Docker ou port publié.
3. Copie des sources dans `/work/src`, installation réelle des dépendances, parcours
   fonctionnel, puis lancement du framework de tests par Test Forge lui-même.

### Windows

Windows Sandbox reçoit :

- le code, les tests et le bootstrap via un montage hôte en lecture seule ;
- un dossier temporaire distinct en écriture pour le seul résultat JSON ;
- Internet pour PowerShell Gallery ;
- des règles sortantes bloquant les réseaux privés IPv4 et IPv6 pour les processus de test ;
- aucun presse-papiers, microphone, caméra, imprimante ou vGPU ;
- PSScriptAnalyzer 1.25.0 et Pester 5.8.0 installés à chaque VM.

Le statut `production_ready=true` exige parser, PSScriptAnalyzer et Pester réussis dans le
Sandbox. Si Windows Sandbox est absent, Marvin conserve l'analyse statique mais refuse la
certification de production.

Depuis v2.235, `windows_validation.py` classe automatiquement le livrable. Le runner Sandbox
actuel certifie PowerShell. Une CLI, un service, une application desktop, un installateur ou
un pilote Windows reste `production_ready=false` tant qu'un runner Windows natif adapté ne
l'a pas réellement exécuté. Une cross-compilation Windows ne constitue jamais cette preuve.

Le blocage n'est pas appliqué globalement à tous les processus de la VM : cela couperait le
canal de contrôle du nouveau client Windows Sandbox 24H2. Il vise PowerShell, CMD et les
outils d'installation courants utilisés par le livrable. Un script qui doit lancer un binaire
arbitraire non couvert devra être dirigé vers le futur runner Hyper-V avec filtrage au niveau
de la carte virtuelle ; Windows Sandbox ne fournit pas nativement une politique « Internet
autorisé mais LAN interdit » complète au niveau vNIC.

## Comparaison des approches Windows

| Approche | Sécurité | Résilience | Maintenance | Performance | Usage retenu |
|---|---|---|---|---|---|
| Windows Sandbox | VM propre à chaque lancement, montage lecture seule | Recréée automatiquement | Faible complexité, une seule instance | Démarrage moyen | Standard PowerShell et installateurs |
| Hyper-V + PowerShell Direct | Isolation forte, réseau contrôlable | Checkpoints et scénarios avec redémarrage | Image, mises à jour et secrets de VM à maintenir | Plus lourd | Futur : AD, services, pilotes, multi-VM |
| Conteneurs Windows | Isolation correcte mais mode Docker distinct | Images reproductibles | Images Windows volumineuses et compatibilité hôte stricte | Rapide après téléchargement | Non retenu comme runner principal |

## Activation

```text
# Target: Windows Pro
# Shell/CLI: Windows PowerShell 5.1
# Privileges: Administrateur
# Objective: Activer Windows Sandbox sans redémarrage automatique
```

```powershell
Set-Location 'C:\Users\Chawb\secretary-ai'
.\scripts\prepare-windows-test-forge.ps1 -EnableSandbox
```

Redémarrer Windows uniquement si le script retourne `3010`.

Le préparateur vérifie aussi les dépendances qui ne sont pas restaurées automatiquement par
DISM. En particulier, `HvHost` doit être en démarrage manuel et les services `RpcSs`, `BFE`
et `MpsSvc` doivent être actifs. Un `HvHost` désactivé provoque l'échec observé du Container
Installer (`0x800706D9`), remonté par CBS sous `0x800F0922`, puis un rollback au redémarrage.
Le script rétablit uniquement `HvHost` de `Disabled` vers `Manual`; il ne modifie ni les
règles du pare-feu, ni VBS/HVCI (Isolation du noyau / Intégrité de la mémoire).

En cas d'échec de maintenance, vérifier l'intégrité de l'image avant une nouvelle tentative :

```text
# Target: Windows 11 Pro 25H2
# Shell/CLI: Windows PowerShell 5.1
# Privileges: Administrateur
# Objective: Vérifier puis réparer le magasin de composants Windows
```

```powershell
DISM.exe /Online /Cleanup-Image /CheckHealth
DISM.exe /Online /Cleanup-Image /RestoreHealth
sfc.exe /scannow
```

## Validation

```text
# Target: Windows Pro
# Shell/CLI: PowerShell
# Privileges: Utilisateur
# Objective: Vérifier la génération sécurisée du fichier WSB
```

```powershell
Set-Location 'C:\Users\Chawb\secretary-ai'
backend\.venv\Scripts\python.exe scripts\test_windows_test_runner.py
```

Le premier vrai test PowerShell ouvrira Windows Sandbox en arrière-plan et peut durer
plusieurs minutes, car les modules sont téléchargés dans une VM neuve.

Le smoke test réel, volontairement séparé des contrôles rapides, se lance avec :

```text
# Target: Windows 11 Pro 25H2
# Shell/CLI: PowerShell
# Privileges: Utilisateur
# Objective: Exécuter parser, PSScriptAnalyzer et trois tests Pester dans une VM jetable
```

```powershell
Set-Location 'C:\Users\Chawb\secretary-ai'
npm run check:windows-test-forge-live
```

Le critère de réussite est `production_ready=true`, `tests_executed=true` et la présence
des cinq preuves `windows_network_guard`, `powershell_parser_vm`, `windows_dependencies`,
`psscriptanalyzer_vm` et `pester_vm`.

## Rollback

```text
# Target: Windows Pro
# Shell/CLI: Windows PowerShell 5.1
# Privileges: Administrateur
# Objective: Désactiver Windows Sandbox
```

```powershell
Disable-WindowsOptionalFeature -Online `
    -FeatureName Containers-DisposableClientVM `
    -NoRestart
```

Redémarrer Windows si demandé par DISM.
