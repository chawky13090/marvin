# Marvin HTTPS LAN

## Contrat actuel

Caddy 2.11.4, téléchargé avec contrôle SHA-512, termine TLS. Next.js écoute uniquement sur
`127.0.0.1:3000` et FastAPI sur `127.0.0.1:8005`. `/marvin-api/*` est transmis à FastAPI
après retrait du préfixe; les autres chemins vont vers Next.js.

Sur Windows 11, la cible de production locale est un service automatique
`MarvinHttpsGateway`, exécuté sous `NT AUTHORITY\LocalService`, sur TCP/443. Le script refuse
d'écraser un listener existant. Le repli 8443 n'est utilisé que si
`-Allow8443Fallback` est demandé explicitement. La règle pare-feu entrante est limitée aux
profils Domaine et Privé et au binaire Caddy épinglé; aucun profil Public n'est ouvert.

## Installation

```text
# Target: Windows 11 x64
# Shell/CLI: Windows PowerShell 5.1
# Privileges: Utilisateur
# Objective: Installer Caddy, vérifier son intégrité et préparer la configuration
```

```powershell
.\scripts\install-marvin-https.ps1 -Port 443
```

```text
# Target: Windows 11 x64
# Shell/CLI: Windows PowerShell 5.1
# Privileges: Administrateur
# Objective: Créer le service à moindre privilège, la règle pare-feu bornée et vérifier TCP/443
```

```powershell
.\scripts\manage-marvin-https-service.ps1 -Action Install -Port 443
```

`start.bat` lit ensuite `runtime/https/state.json`; il ne contient plus de port HTTPS codé
en dur. Un service installé reste indépendant des arrêts frontend/backend.

## Confiance et révocation

L'autorité est propre à l'installation. Le script calcule l'empreinte exacte, vérifie le
magasin après import et conserve uniquement empreinte, SHA-256 et portée dans un état atomique.

```text
# Target: Windows 11 x64
# Shell/CLI: Windows PowerShell 5.1
# Privileges: Utilisateur
# Objective: Approuver l'autorité Marvin pour l'utilisateur courant
```

```powershell
.\scripts\trust-marvin-https.ps1 -Scope CurrentUser
```

```text
# Target: Windows 11 x64
# Shell/CLI: Windows PowerShell 5.1
# Privileges: Utilisateur, ou Administrateur pour LocalMachine
# Objective: Révoquer uniquement l'autorité suivie par Marvin
```

```powershell
.\scripts\untrust-marvin-https.ps1 -Scope CurrentUser
```

Windows affiche volontairement une seconde confirmation système lors de la suppression d'une
racine de confiance. Marvin ne contourne pas cette protection. Cliquer sur `Oui` uniquement
pendant une révocation explicitement demandée.

## Journalisation et sécurité

Caddy ne produit aucun journal d'accès : URLs, requêtes, cookies et en-têtes ne sont donc pas
dupliqués. Les mutations de confiance et de service produisent des événements JSONL minimisés
dans `runtime/logs/https-security.jsonl`. Rotation à 10 Mio, rétention maximale 90 jours et
30 archives. Aucun certificat, token, cookie, contenu de requête ou message d'erreur brut n'y
est écrit.

Les en-têtes HSTS, `nosniff`, `Referrer-Policy` et `Permissions-Policy` sont posés à la
passerelle. L'interface d'administration Caddy reste sur `127.0.0.1:2019`.

## Validation

```powershell
$env:MARVIN_HTTPS_LIVE = '1'
.\backend\.venv\Scripts\python.exe .\scripts\test_https_gateway.py
Remove-Item Env:\MARVIN_HTTPS_LIVE
.\scripts\get-marvin-runtime-status.ps1
```

Critères : service `Running`, compte `LocalService`, un listener 443, aucun listener 8443,
pare-feu `Domain, Private`, santé HTTPS `ok`, frontend/backend liés uniquement à loopback.

## Rollback

Rollback du service sans toucher aux données ni au certificat :

```powershell
.\scripts\manage-marvin-https-service.ps1 -Action Uninstall
```

Rollback complet, qui arrête le runtime puis demande les confirmations nécessaires pour
révoquer les portées suivies avant suppression :

```powershell
.\scripts\rollback-marvin-https.ps1
```

HTTP `3000/8005` reste limité au PC principal. Aucune base ou donnée métier n'est modifiée.

## Limites restantes

- Les parcours d'installation/révocation de l'autorité sur Android, iOS, macOS et Linux ne
  sont pas encore automatisés; SEC-001 reste donc `MITIGATED`, pas `VERIFIED`.
- Le service utilise un runtime sous le profil utilisateur avec une ACL dédiée au SID
  `LocalService`. L'installeur final pourra déplacer ce runtime vers `%ProgramData%\Marvin`
  lors d'une migration explicitement réversible.
