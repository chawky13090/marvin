# Installation portable de Marvin sous Windows

Cette procédure couvre Windows 11 et Windows Server 2019/2022/2025. Le socle Marvin
(frontend, backend, Ollama et avatar) doit pouvoir être installé sans Docker, Hyper-V,
Windows Sandbox ni GPU. Ces composants restent des capacités avancées optionnelles : leur
absence dégrade Test Forge, mais ne bloque ni le chat, ni les outils ordinaires.

Après installation ou vérification, l'état réel de chaque capacité est écrit dans
`data/install-capabilities.json` avec l'un des états `available`, `degraded` ou
`unavailable`, une explication et l'action corrective adaptée à la machine.

Procédure pas à pas pour déployer Marvin sur un Windows Server dédié, avec accès
internet et droits administrateur. Suivez les étapes dans l'ordre — chacune indique
le résultat attendu avant de passer à la suivante.

---

## 0. Prérequis

- [ ] Windows Server (2019, 2022 ou 2025 — Desktop Experience ou Core), avec accès administrateur.
- [ ] Accès internet sortant (téléchargement de Python/Node/Ollama + des modèles IA, plusieurs Go).
- [ ] Au moins **20 Go d'espace disque libre** (dépendances + modèles IA + marge).

> ⚠️ **Ne copiez jamais** les dossiers `.venv`, `node_modules` ou `.next` d'une autre
> machine — ils contiennent des binaires compilés pour CET ordinateur précis et
> provoqueront des erreurs.
>
> ⚠️ **Attention au dossier `data/`** (et `backend\data\`) : il contient VOS conversations,
> mémoires, captures d'écran, sauvegardes et éventuellement une clé de compte de service
> Google — des données personnelles/sensibles, pas du code. Pour un **nouveau** déploiement
> (comme un serveur boutique qui doit démarrer propre), il ne faut **surtout pas** le copier.
> Un simple copier-coller du dossier `secretary-ai` l'embarquerait par erreur.

### Préparer un paquet propre à transférer

Depuis CE poste (celui qui a le projet actuellement), lancez
**`PREPARER-PAQUET-BOUTIQUE.bat`** — il crée une copie du projet à côté, sans `data/`,
`backend\data\`, `.venv`, `node_modules`, `.next`, ni `.env.local`. C'est CE dossier
qu'il faut transférer sur le serveur (clé USB, partage réseau) — pas l'original.

**Résultat attendu** : `[OK] Aucun dossier data\` / `[OK] Aucun backend\data\` /
`[OK] Aucun .env.local` affichés à la fin.

---

## 1. Installer les dépendances (Python, Node.js, Ollama)

Double-cliquez sur **`INSTALLER-NOUVEAU-PC.bat`** (pas besoin d'être administrateur,
sauf si `winget` est absent et qu'une installation directe est nécessaire — dans ce
cas, exécutez-le via clic droit → *Exécuter en tant qu'administrateur*).

> ⚠️ **Ne l'ouvrez/exécutez JAMAIS depuis PowerShell ISE ou en collant son contenu
> dans une console PowerShell** — c'est un script **batch** (`cmd.exe`), pas du
> PowerShell ; ISE essaierait d'interpréter `@echo off` et le reste comme du code
> PowerShell et échouerait avec des erreurs de syntaxe. Sur un Windows Server sans
> Explorateur (Server Core), lancez-le depuis une invite avec `cmd /c "chemin\vers\
> INSTALLER-NOUVEAU-PC.bat"` ou, depuis PowerShell, `.\INSTALLER-NOUVEAU-PC.bat`.

Le script :
1. Vérifie/installe Python, Node.js et Ollama (via `winget`, ou en repli direct si
   `winget` est absent — fréquent sur Windows Server).
2. Recrée proprement `backend\.venv` et `node_modules` pour CETTE machine.
3. Télécharge les modèles locaux de confidentialité : `qwen2.5:7b`,
   `nomic-embed-text` pour la mémoire sémantique et `llava-phi3` pour la vision. Un échec
   de téléchargement est signalé comme capacité dégradée plutôt que masqué.
4. Installe l'avatar Electron et crée dynamiquement le raccourci `Marvin Avatar` sur le
   Bureau, sans chemin lié au compte de développement. L'avatar est aussi accessible depuis
   le robot en haut de la barre latérale et par `Ctrl+Maj+Espace`.

**Résultat attendu** : le message `INSTALLATION TERMINEE !` à la fin, sans `[ERREUR]`
ni `[X]` au-dessus.

> Si le script s'arrête après avoir installé Python ou Node.js pour la première
> fois, c'est normal — **fermez la fenêtre et relancez le script** (le `PATH` doit
> être rechargé).

> Certaines installations Python (constaté sur un Windows Server réel) n'incluent
> pas `pip` par défaut. Le script le détecte et le répare automatiquement
> (`ensurepip`, sans téléchargement) — vous verrez `[ATTENTION] pip introuvable...`
> suivi de `[OK] pip réinstallé avec succès` si c'était le cas, rien à faire de plus.

---

## 2. Vérifier l'installation

Double-cliquez sur **`VERIFIER-INSTALLATION.bat`**.

**Résultat attendu** : les composants du socle portent `[OK]`. Docker, Hyper-V, Sandbox ou
les VM de certification peuvent porter `[DEGRADE]` sans rendre Marvin inutilisable. Les
erreurs `[X]` concernent le socle et doivent être corrigées avant le démarrage.

## 2bis. Niveaux de capacités

- Socle sans élévation : chat, outils, Code Workspace, Ollama Cloud/local et avatar.
- Test Forge conteneurisé : Docker Desktop, facultatif, avec accès Internet uniquement lors
  des passages d'installation explicitement prévus.
- Certification native : Hyper-V et VM Debian/Windows préparées, facultatifs et nécessitant
  une élévation ainsi qu'éventuellement un redémarrage. L'installateur ne modifie pas ces
  fonctions système silencieusement.

---

## 3. Premier démarrage en mode production

Double-cliquez sur **`START-PRODUCTION.bat`** (différent de `start.bat`, qui est le
mode développement utilisé pour itérer sur le code — pas pour un serveur laissé sans
surveillance).

Au premier lancement, le script **construit** le frontend (`npm run build`, 1 à 3
minutes) avant de démarrer — les lancements suivants réutilisent ce build et sont
quasi instantanés.

**Résultat attendu** : trois lignes `Frontend : ...`, `Backend : ...`, `API docs : ...`
affichées, et `http://localhost:3000` accessible dans un navigateur sur le serveur.

> Si vous modifiez le code plus tard, reconstruisez avec :
> `START-PRODUCTION.bat rebuild`

---

## 4. Accès depuis le réseau de la boutique + démarrage automatique

Marvin doit être accessible depuis les autres postes de la boutique (pas seulement
en local sur le serveur), et doit repartir **tout seul** après un reboot ou une
coupure de courant. Les deux sont gérés par le même script — exécutez **en tant
qu'administrateur** :

**`INSTALLER-DEMARRAGE-AUTO.bat`**

Il fait deux choses :
1. **Ouvre le pare-feu Windows** (ports 3000 frontend / 8005 backend) pour l'accès
   réseau — sans ça, seul le serveur lui-même pourrait accéder à Marvin.
2. **Enregistre une tâche planifiée** qui relance Marvin automatiquement à chaque
   démarrage du serveur.

**Résultat attendu** : `[OK] Ports 3000 (frontend) et 8005 (backend) ouverts` puis
`[OK] Tâche planifiée créée`. Testez immédiatement sans redémarrer avec la commande
affichée à l'écran (`schtasks /run /tn "..."`), puis :
- `http://localhost:3000` répond depuis le serveur lui-même une minute après ;
- `http://<IP-DU-SERVEUR>:3000` répond depuis un **autre poste de la boutique**
  (trouvez l'IP du serveur avec `ipconfig`, champ « Adresse IPv4 »).

> ℹ️ Cette tâche tourne sous le compte SYSTEM (aucune session utilisateur requise,
> démarre avant même l'écran de connexion). Contrepartie : les fonctionnalités qui
> ont besoin d'une session de bureau interactive (notifications visuelles Windows,
> presse-papiers) peuvent être indisponibles dans ce mode. Si vous en avez besoin au
> quotidien sur ce serveur, dites-le et on adaptera la tâche planifiée à un compte
> utilisateur dédié avec ouverture de session automatique.

---

## 4bis. Serveur SANS GPU → mode Cloud Total

> ⚠️ **Cette étape est spécifique à un serveur SANS carte graphique** (comme celui de
> la boutique). Elle envoie toutes les données au cloud sans exception, y compris
> les données sensibles (emails, mots de passe, SSH) normalement gardées en local.
> **Ne l'appliquez jamais sur un poste de travail normal qui a un GPU** — sur une
> machine avec GPU, Marvin fonctionne déjà bien en local, ce mode n'y apporterait
> rien et enverrait inutilement des données au cloud. Le script détecte lui-même la
> présence d'un GPU et demande une confirmation explicite s'il en trouve un.

Ce serveur n'a pas de carte graphique : faire tourner les modèles IA localement
(sur CPU) serait trop lent pour un usage quotidien. Une fois Marvin démarré et un
modèle cloud installé (`ollama pull deepseek-v4-flash:cloud` ou équivalent),
exécutez **`CONFIGURER-CLOUD-TOTAL.bat`**.

Ce script bascule tout (agent/chat/analyse) vers le cloud, **sans exception de
sensibilité** — équivalent au préréglage *Ultra débridé* de *Réglages → Modèle IA*,
appliqué directement via l'API (pratique sans navigateur à portée de main sur un
serveur). Deux choses **ne changent jamais**, quel que soit ce réglage :
- Le garde-fou système contre les commandes destructrices (formatage disque,
  suppression système...) — aucun mode ne le désactive.
- L'OCR/vision généraliste (photos, scans de documents) reste **local** par défaut
  — plus lent sans GPU, mais rien d'envoyé au cloud pour ce type de contenu
  potentiellement sensible (factures clients...). Seul le pipeline dédié
  « captures d'écran → documentation » (v2.175) utilise le cloud pour l'analyse
  d'images, en connaissance de cause.

**Résultat attendu** : `[OK] Configuration appliquée`, avec le nom du modèle cloud
choisi affiché. Vérifiable ensuite dans *Réglages → Modèle IA* (carte *Ultra
débridé* affichée comme active).

> ℹ️ Le modèle cloud est choisi **automatiquement parmi ceux réellement installés**
> (jamais un nom figé en dur) — les fournisseurs cloud retirent/renomment des
> modèles régulièrement (constaté en réel : deux modèles recommandés dans une
> session de développement ont été retirés ~2 jours plus tard). Si vous ajoutez ou
> retirez des modèles cloud plus tard (`ollama pull`/`ollama rm`), relancez
> simplement le script pour ré-appliquer le meilleur choix disponible.

---

## 6. Configuration propre à cette installation

- [ ] **Identité document** (auteur, organisation, logo, pied de page) : demandez
      directement à Marvin dans le chat, ou remplissez-la dans *Réglages → Connexions
      → Identité des documents*.
- [ ] **Comptes connectés** (Google Agenda/Gmail, Outlook, recherche web...) : à
      configurer dans *Réglages → Connexions*, propre à chaque déploiement — jamais
      copié d'une autre machine.
- [ ] **Cas particulier — migration** (PAS le cas d'un nouveau serveur boutique, à
      ignorer par défaut) : si le but est de reprendre l'historique d'un poste
      existant plutôt que de démarrer propre, copiez alors SON dossier `data/`
      complet AVANT le premier démarrage (réglages, compétences, mémoire, clé de
      compte de service Google). `PREPARER-PAQUET-BOUTIQUE.bat` l'exclut exprès —
      dans ce cas de migration, recopiez-le manuellement à la place.
- [ ] **Niveau de performance** : Marvin détecte automatiquement le matériel du
      serveur (CPU/RAM/GPU) et adapte les modèles/leviers — rien à faire ici.

---

## En cas de problème

1. Relancez `VERIFIER-INSTALLATION.bat` — il identifie précisément ce qui manque.
2. Consultez les fenêtres `SecretaryAI - Backend` et `SecretaryAI - SearXNG` restées
   ouvertes en arrière-plan pour les messages d'erreur détaillés.
3. `http://localhost:8005/api/health` doit répondre avec un JSON contenant `"status":"ok"`
   et le nombre d'outils chargés — si ce n'est pas le cas, le backend a un problème
   de démarrage (voir sa fenêtre de log).
