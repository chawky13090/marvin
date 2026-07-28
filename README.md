# Marvin — assistant IA local pour technicien informatique

**Version 2.421.0**

Marvin est un assistant personnel et technique piloté par un LLM. Il combine une interface
web, un moteur agentique, une mémoire locale et 344 outils pour agir sur Windows, les
documents, le réseau, les e-mails, les calendriers et les systèmes distants.

La version 2.250 ajoute un suivi durable des Coding Missions directement dans le chat, une
lecture vocale strictement sérialisée et un avatar de bureau Electron optionnel. Sa fenêtre
compagnon conversation/compacte conserve les échanges récents et la progression de la mission
Code; elle est accessible par le Bureau, le robot de la barre latérale ou `Ctrl+Maj+Espace`.
Voir `DESKTOP-AVATAR.md`.

Le fonctionnement est local par défaut : Ollama exécute les modèles, SQLite conserve les
données applicatives et Qdrant assure la recherche vectorielle. Le cloud est facultatif,
explicitement activé et protégé par les modes de confidentialité de Marvin.

## Capacités principales

- Chat en streaming avec sélection automatique du modèle et appels d’outils multi-étapes.
- Administration Windows, inventaire matériel, monitoring, GUI Automation et commandes.
- Diagnostic réseau, SSH, SNMP, Nmap, topologie et suivi des équipements.
- Lecture et génération Word, PDF, Excel et PowerPoint, OCR et recherche documentaire.
- Gmail, Outlook, Google Calendar, iCal, tâches, notes et briefings proactifs.
- Les outils e-mail sont multi-comptes, compatibles OAuth, bornés et conservent une
  confirmation obligatoire avant chaque envoi manuel.
- Recherche web avec navigateur réel et SearXNG local optionnel.
- Council v2 avec cinq familles Ollama Cloud, critique croisée et arbitrage traçable.
- Model Market avec routage par rôle, scorecards passives, parc Ollama Cloud
  auto-synchronisé et Research Swarm à cinq cellules spécialisées.
- Evolution Lab avec promotion mesurée et rollback, Mission Canvas avec pause, reprise et retry.
- Frontier Arena compare plusieurs assistants sur le même corpus ; Evidence Fabric relie
  chaque affirmation à ses sources et mesure la dette épistémique.
- Les duels Arena masquent l'identité des systèmes jusqu'au vote et notent séparément
  exactitude, complétude, preuves et utilité.
- Adaptive Team choisit entre Research Swarm, Cortex Search et Council, et peut enchaîner
  recherche sourcée puis résolution multi-stratégies pour les demandes explicitement complexes.
- Code Forge impose contrat, revues, réparations et gatekeeper ; Test Forge exécute ensuite
  les contrôles initiaux hors ligne, installe les dépendances dans Debian 13 avec Internet,
  relance lui-même les tests et utilise Windows Sandbox pour PowerShell quand disponible.
- Engineering Knowledge Radar actualise un catalogue fermé de documentations officielles,
  sélectionne uniquement celles du langage demandé et transmet fraîcheur, URL et SHA-256 à
  Code Forge sans traiter le contenu documentaire comme une instruction exécutable.
- Code Workspace centralise les projets de développement, phases, snapshots, fichiers,
  preuves de tests, toolchains certifiées et sources officielles, avec reprise par mission.
  Une demande peut être saisie directement sans dépôt existant : Marvin crée alors un dépôt
  Git et un worktree isolés. Les mêmes fonctions de création, suivi, reprise et annulation
  sont accessibles depuis le chat avec confirmation des opérations mutables.
- Repository Intelligence analyse le dépôt sans exécuter son code, applique les instructions
  `AGENTS.md`/`CLAUDE.md` par portée et crée un worktree Git isolé par mission. Le mode Auto
  est borné et toute certification Windows exige une exécution native dans la VM adaptée.
- Le superviseur Auto persiste sa file, reprend après redémarrage, respecte les budgets,
  peut être arrêté depuis Code Workspace et applique uniquement les livrables acceptés dans
  le worktree. Le checkout utilisateur n'est jamais modifié automatiquement.
- Une mission Auto suit `until_success` : les 120 minutes sont une tranche d'exécution par
  tentative, pas une durée de vie. Les erreurs récupérables déclenchent une reprise bornée;
  un blocage réel met la mission en pause sans la déclarer terminée ni réussie.
- Tous les chemins utilisateur passent par les Known Folders Windows : Bureau, Documents,
  Téléchargements, OneDrive et redirections d'entreprise suivent le profil courant. Les
  alias `Bureau\\fichier` et les variables d'environnement sont résolus dynamiquement. La
  configuration MCP se génère avec `backend\\.venv\\Scripts\\python.exe backend\\mcp_server.py --print-config`.
- La Bibliothèque de Code Workspace sépare les ressources lourdes locales dans
  `%LOCALAPPDATA%\Marvin` (ISO, VHDX, worktrees, tests, caches) des livrables visibles dans
  le Known Folder `Documents\Marvin`. Un disque réseau ou un dossier cloud est refusé pour
  la racine machine afin de protéger les performances et l'intégrité des VM.
- VM Lab conserve une preuve d'intégrité liée à la taille et à la date des ISO, invalide
  automatiquement la preuve si un média change et prépare deux VM Hyper-V génération 2
  isolées des anciennes : Windows 11 avec Secure Boot/vTPM et Debian avec le modèle UEFI CA.
- Marvin peut installer ou recréer lui-même ces deux VM depuis Code Workspace ou l'outil
  `vm_lab_install`. Le job persistant vérifie le média, exécute l'installation sans assistance,
  reprend les erreurs récupérables, crée `Marvin-Clean` et conserve les preuves sans exposer
  les secrets DPAPI. Une seule installation destructive est admise à la fois et exige une
  confirmation explicite portant sur le nom exact de la VM remplacée.
- Le runner Hyper-V exécute nativement les livrables Windows en ligne de commande dans une
  VM existante restaurée depuis un checkpoint. PowerShell Direct transporte les fichiers sans
  SMB, la carte réseau est coupée pendant les tests et le secret invité reste chiffré par DPAPI.
  Marvin ne déclare jamais ce backend prêt tant que la VM et le checkpoint ne sont pas vérifiés.
  L'accès hôte s'active une fois avec `ACTIVER-HYPERV-MARVIN.bat`; cette opération ne coupe
  aucune carte réseau physique et ne donne pas les privilèges administrateur à Marvin.
- Voix, transcription, synthèse vocale, images et vidéo locale.
- Compétences Markdown apprenantes avec ressources, statistiques, versions et rollback.
- Garde-fous conversationnels : une réponse de quiz ou une rédaction simple ne déclenche pas d'outil.
- Devis, facturation, documentation d’intervention et base de connaissances IT.

## Architecture

| Couche | Technologie | Port |
|---|---|---:|
| Interface | Next.js 16, React 19 | 3000 |
| API et agent | FastAPI, Python | 8005 |
| Modèles | Ollama | 11434 ou port local de repli |
| Données | SQLite et Qdrant local | local |

Le frontend utilise [lib/backend.js](lib/backend.js) comme source unique pour joindre
FastAPI. Le backend utilise [backend/app_version.py](backend/app_version.py) comme source
unique de version. La description détaillée des responsabilités se trouve dans
[ARCHITECTURE.md](ARCHITECTURE.md).

## Installation Windows

Sur une nouvelle machine :

```text
INSTALLER-NOUVEAU-PC.bat
VERIFIER-INSTALLATION.bat
```

Ne copiez jamais `node_modules`, `.next` ou `backend/.venv` entre deux machines. Ces dossiers
contiennent des binaires dépendants du poste. Pour migrer une installation existante, copiez
uniquement le code et, si nécessaire, le dossier `data/` afin de conserver la mémoire et les
réglages.

Pour lancer Marvin :

```text
start.bat
```

Puis ouvrez [http://localhost:3000](http://localhost:3000).

Pour arrêter uniquement les services Marvin (Ollama reste disponible) :

```text
stop.bat
```

## Développement

Frontend :

```powershell
npm install
npm run dev
```

Backend, depuis `backend/` :

```powershell
.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8005
```

Contrôle rapide pendant le développement :

```powershell
npm run check:quick
```

Contrôle de livraison, services arrêtés (inclut le build Next.js) :

```powershell
npm run check
```

Contrôle fonctionnel quand Marvin est déjà démarré :

```powershell
npm run check:live
```

L'orchestrateur valide le runtime, les modules natifs Node.js, les dépendances Python,
l'architecture, le lint et, selon le mode, le build ou les contrats HTTP, les 34 pages et le
chat. Il ne charge jamais Qdrant depuis un second processus.

## Données et configuration

- `.env.local` : configuration locale, jamais versionnée.
- `data/secretary.db` : conversations, réglages, tâches et données métier.
- `data/qdrant/` : index vectoriels locaux.
- `data/skills/` : compétences et ressources personnelles.
- `data/audit.jsonl` et `data/bug_log.jsonl` : traces d’actions et erreurs réelles.

La santé du backend est disponible sur `GET /api/health`. Cette route expose la version,
l’état d’Ollama et les nombres réels d’outils enregistrés et spécifiés.

Test Forge applique deux niveaux Linux : des conteneurs Debian jetables pour les contrôles
rapides, puis la VM Hyper-V `Marvin-Debian13-TestForge` lorsqu'un vrai `systemd` ou une
installation système doit être exécuté. Le checkpoint `Marvin-Clean` est restauré avant et
après chaque passage. Un résultat réussi peut être rouvert depuis Code Workspace grâce à un
checkpoint temporaire, puis supprimé par l'action « Restaurer la base saine ».

## Documentation

- [AGENTS.md](AGENTS.md) : contexte opérationnel destiné aux agents de développement.
- [ARCHITECTURE.md](ARCHITECTURE.md) : frontières, responsabilités et invariants du code.
- [INSTALLATION.md](INSTALLATION.md) : installation et dépannage détaillés.

Projet propriétaire — tous droits réservés.
