# VM Lab Marvin — installation et validation

Cible technique : Windows 11 hôte avec Hyper-V, VM Debian 13.6 et Windows 11 Pro 25H2
Versions : Marvin 2.243.0, PowerShell 5.1, Hyper-V génération 2
Niveau requis : N2 / N3
Impact de production : Modéré — recréation de la VM explicitement choisie
Fenêtre de maintenance : 30 à 120 minutes selon le média et le débit Internet
Privilèges requis : membre `Hyper-V Administrators`; administrateur uniquement pour activer Hyper-V initialement
Durée indicative : Debian 20–45 minutes; Windows 45–120 minutes
Sauvegarde préalable : checkpoint ou export externe si une VM portant le même nom doit être conservée
Plan de rollback : le job ne touche qu'au nom de VM confirmé; restaurer un export externe si l'ancienne VM devait être conservée

## Architecture

- Bibliothèque machine : `%LOCALAPPDATA%\Marvin` ou `MARVIN_MACHINE_ROOT`.
- Profils gérés : `Marvin-Debian13-TestForge` et `Marvin-Windows11-TestForge`.
- Un seul job d'installation actif à la fois dans `data/vm_lab_install_job.json`.
- Logs bornés côté API; fichier complet sous `data/vm_lab_jobs/`.
- État propre attendu : VM arrêtée et checkpoint `Marvin-Clean`.
- Pendant l'installation, seule la carte virtuelle de l'invité utilise `Default Switch`.
- Pendant Test Forge Windows, les cartes de la VM sont déconnectées; le réseau physique de l'hôte n'est jamais modifié.
- Test Forge Debian restaure `Marvin-Clean` avant et après chaque exécution native. Le réseau
  invité reste disponible pendant le test pour installer les dépendances; aucun partage hôte,
  port publié ou secret utilisateur n'est monté dans la VM.

## Lancement par Marvin

Depuis `/code`, onglet **Bibliothèque**, vérifier les empreintes ISO puis sélectionner
**Installer ou recréer debian13** ou **Installer ou recréer windows11**. Le dialogue confirme
le nom exact de la VM remplacée.

Depuis le chat, Marvin utilise l'outil `vm_lab_install` :

- `action=status` : lecture sans effet de bord;
- `action=install`, `profile=debian13|windows11`, `confirmed=true` : recréation confirmée.

Le backend expose les mêmes contrats :

- `GET /api/vm-lab/status`;
- `POST /api/vm-lab/verify-isos`;
- `GET /api/vm-lab/install`;
- `POST /api/vm-lab/install`.

## Contrats invités

### Debian 13

- root verrouillé et aucun mot de passe utilisateur;
- authentification SSH Ed25519, clé privée chiffrée DPAPI côté hôte;
- `marvin` sans sudo général; seules l'extinction propre et l'entrée bornée
  `/usr/local/sbin/marvin-test-forge-runner` sont autorisées;
- l'entrée bornée accepte uniquement un identifiant `linux-forge-*` et exécute le harnais copié
  sous `/var/tmp` avec privilèges root dans cette VM jetable;
- Python, build-essential, ShellCheck, Bats, OpenSSH et services Hyper-V installés;
- Secure Boot avec `MicrosoftUEFICertificateAuthority`.

### Cycle d'un test Debian natif

1. VM arrêtée et restauration du checkpoint immuable `Marvin-Clean`;
2. démarrage avec le réseau invité `Default Switch`;
3. copie SSH du bundle uniquement, puis exécution de `integration.sh` et Bats;
4. si le test réussit, création d'un checkpoint temporaire `Marvin-Result-<run_id>`;
5. arrêt et restauration immédiate de `Marvin-Clean`;
6. depuis Code Workspace, l'utilisateur peut ouvrir le résultat temporaire pour un contrôle
   manuel. Aucune autre certification ne démarre tant que cette session est ouverte;
7. « Restaurer la base saine » arrête la VM, restaure `Marvin-Clean` et supprime les résultats.

### Windows 11

- Windows 11 Pro, vTPM et Secure Boot `MicrosoftWindows`;
- secret invité aléatoire conservé sous DPAPI;
- AutoLogon limité au provisionnement WinGet, puis supprimé avec son mot de passe;
- compte final `marvin` non administrateur, membre de `Remote Management Users`;
- Python 3.13, Node.js LTS, Git, Go et .NET 10 vérifiés par leur exécutable réel;
- le média Autounattend contenant le secret est détaché et détruit après succès ou échec.

## Gestion du dialogue VMConnect

Les installations et tests normaux sont sans interface : PowerShell Direct et SSH sont
prioritaires. Si l'utilisateur demande une observation visuelle, Marvin doit :

1. appeler `pc_gui_read` sur `Se connecter à <nom exact de VM>`;
2. utiliser l'`automation_id` réellement retourné, notamment `m_ConnectButton` seulement s'il est observé;
3. appeler `pc_gui_click` après confirmation explicite;
4. relire la liste des fenêtres pour prouver la disparition du dialogue.

Aucune coordonnée fixe ne doit être conservée.

## Validation

```text
# Target: hôte Windows 11
# Shell/CLI: PowerShell 5.1
# Privileges: membre Hyper-V Administrators
# Objective: exécuter le smoke test Windows natif et vérifier l'isolation
```

```powershell
$env:PYTHONIOENCODING = 'utf-8'
& .\backend\.venv\Scripts\python.exe .\scripts\smoke_hyperv_runner_live.py
```

Critères : `production_ready=true`, compte invité non administrateur, deux étapes réussies,
réseau déconnecté pendant l'exécution et checkpoint restauré avant/après.

## Arrêt et reprise

- Un job reste lisible après redémarrage du backend; son PID et son résultat sont réconciliés.
- Une erreur récupérable WinGet est retentée trois fois avec actualisation de source et backoff.
- Une erreur définitive laisse une preuve `failed`; Marvin ne crée pas de fausse certification.
- Ne jamais arrêter brutalement la VM pendant une installation MSI. Si Windows a terminé mais
  que la finalisation hôte a échoué, exécuter `scripts/finalize-windows-vm-lab.ps1`.
