# Test Forge Hyper-V Windows

L'activation initiale la plus simple consiste à double-cliquer sur
`ACTIVER-HYPERV-MARVIN.bat`, accepter l'UAC, puis fermer et rouvrir la session Windows.
L'activateur ajoute uniquement le compte interactif au groupe local `Administrateurs Hyper-V`.
Il ne désactive aucune carte réseau de l'hôte et ne crée ni ne modifie aucune VM.

Cible technique : Windows 11 Pro ou Enterprise avec Hyper-V  
Versions : Windows 10/11 invités compatibles PowerShell Direct  
Niveau requis : N3  
Impact de production : Modéré lors du provisionnement, nul pendant un audit simple  
Fenêtre de maintenance : nécessaire uniquement pour créer/configurer la VM  
Privilèges requis : Administrateur pour provisionner; membre Hyper-V Administrators ensuite  
Durée indicative : 30 à 90 minutes selon l'installation Windows invitée  
Sauvegarde préalable : checkpoint de référence obligatoire  
Plan de rollback : supprimer l'association dans Marvin; aucune VM n'est supprimée automatiquement

## Objectif

Le runner exécute nativement les CLI et suites de tests Windows dans une VM Hyper-V restaurée
avant et après chaque mission. Le canal de contrôle utilise PowerShell Direct et ne nécessite
aucun port WinRM, SSH ou RDP. Les sources sont copiées par la session VM, jamais par SMB.

## Contrat de sécurité

- VM Génération 2 et checkpoint propre nommé par défaut `Marvin-Clean`;
- compte invité dédié non administrateur;
- mot de passe chiffré par DPAPI pour le seul compte Windows exécutant Marvin;
- carte réseau Hyper-V déconnectée par l'hôte pendant l'exécution;
- restauration du checkpoint avant et après le test;
- `production_ready=false` si le compte est administrateur, si un checkpoint manque ou si
  une étape échoue;
- aucune suppression ou création automatique de VM par Marvin.

Ce premier runner natif fonctionne hors ligne. Les toolchains et dépendances nécessaires
doivent être présentes dans le checkpoint. L'accès Internet contrôlé sera ajouté séparément
avec un réseau Hyper-V dédié; Windows Sandbox connecté n'est pas utilisé pour du code arbitraire
car Microsoft avertit qu'il peut exposer le réseau interne.

## Audit du poste

```text
# Target: Windows 11 Pro/Enterprise
# Shell/CLI: Windows PowerShell 5.1
# Privileges: Utilisateur pour l'audit; Administrateur pour les actions
# Objective: Vérifier Hyper-V, les services, le groupe opérateur, la VM et le checkpoint
```

```powershell
Set-Location 'C:\Users\Chawb\secretary-ai'
.\scripts\prepare-hyperv-test-forge.ps1 -VMName 'Marvin-TestForge'
```

Le script est en lecture seule par défaut. Pour ajouter explicitement l'utilisateur courant au
groupe Hyper-V Administrators :

```powershell
.\scripts\prepare-hyperv-test-forge.ps1 -GrantCurrentUser -Confirm
```

Une fermeture/réouverture de session Windows est alors nécessaire.

Pour une VM existante, arrêtée et déjà préparée :

```powershell
.\scripts\prepare-hyperv-test-forge.ps1 `
    -VMName 'Marvin-TestForge' `
    -CheckpointName 'Marvin-Clean' `
    -CreateCheckpoint `
    -Confirm
```

## Configuration dans Marvin

Ouvrir **Code Workspace > Windows VM**, puis saisir le nom exact de la VM, le checkpoint et
le compte invité non administrateur. Le secret n'est jamais relu par l'interface.

## VM Lab Marvin

Les médias sont classés sous `%LOCALAPPDATA%\Marvin\library\iso` et leur preuve d'intégrité
est visible dans **Code Workspace > Bibliothèque**. `PROVISIONNER-VM-LAB-MARVIN.bat` crée deux
VM arrêtées sans installer automatiquement les systèmes :

- `Marvin-Windows11-TestForge` : génération 2, 6 Gio, 4 vCPU, VHDX dynamique 80 Gio,
  Secure Boot Microsoft Windows et vTPM;
- `Marvin-Debian13-TestForge` : génération 2, 4 Gio, 4 vCPU, VHDX dynamique 40 Gio,
  Secure Boot Microsoft UEFI Certificate Authority;
- `Default Switch` n'est utilisé que pour l'installation et les mises à jour;
- aucun checkpoint automatique; le checkpoint `Marvin-Clean` est créé après installation,
  mises à jour, toolchains et compte invité dédié.

Le provisionneur préserve toute VM existante, refuse une ISO modifiée, accepte `-WhatIf` et
ne touche jamais aux cartes réseau physiques. `SUPPRIMER-ANCIENNES-VM.bat` préserve toujours
les noms `Marvin-*`; son rapport est `data/hyperv-legacy-removal-result.json`.
Lorsque ce rapport indique `blocked_corrupt_inventory`, lancer `AUDITER-MAGASIN-HYPERV.bat`
et accepter l'UAC. Cet audit est en lecture seule et produit `data/hyperv-store-audit.json`;
il doit être analysé avant de retirer manuellement des inscriptions cassées de `ProgramData`.

## Validation

```text
# Target: Windows 11
# Shell/CLI: PowerShell
# Privileges: Utilisateur
# Objective: Vérifier le contrat du runner sans démarrer de VM
```

```powershell
Set-Location 'C:\Users\Chawb\secretary-ai'
backend\.venv\Scripts\python.exe scripts\test_hyperv_test_runner.py
```

## Limites actuelles

- les applications graphiques nécessitent encore un runner interactif avec assertions UI;
- les installateurs et pilotes nécessitent une VM administrateur distincte;
- le runner natif hors ligne ne télécharge aucune dépendance pendant le test;
- une VM Windows et sa licence ne sont pas fournies automatiquement.
