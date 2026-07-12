# Installation de Marvin sur un Windows Server (poste boutique)

Procédure pas à pas pour déployer Marvin sur un Windows Server dédié, avec accès
internet et droits administrateur. Suivez les étapes dans l'ordre — chacune indique
le résultat attendu avant de passer à la suivante.

---

## 0. Prérequis

- [ ] Windows Server (2019, 2022 ou 2025 — Desktop Experience ou Core), avec accès administrateur.
- [ ] Accès internet sortant (téléchargement de Python/Node/Ollama + des modèles IA, plusieurs Go).
- [ ] Au moins **20 Go d'espace disque libre** (dépendances + modèles IA + marge).
- [ ] Le dossier `secretary-ai` copié sur le serveur (clé USB, partage réseau, ou `git clone`).

> ⚠️ Ne copiez **jamais** les dossiers `.venv`, `node_modules` ou `.next` d'une autre
> machine — ils contiennent des binaires compilés pour CET ordinateur précis et
> provoqueront des erreurs. Le dossier `data/` en revanche **doit** être copié s'il
> existe déjà (réglages, compétences, mémoire, clé Google) — voir étape 6.

---

## 1. Installer les dépendances (Python, Node.js, Ollama)

Double-cliquez sur **`INSTALLER-NOUVEAU-PC.bat`** (pas besoin d'être administrateur,
sauf si `winget` est absent et qu'une installation directe est nécessaire — dans ce
cas, exécutez-le via clic droit → *Exécuter en tant qu'administrateur*).

Le script :
1. Vérifie/installe Python, Node.js et Ollama (via `winget`, ou en repli direct si
   `winget` est absent — fréquent sur Windows Server).
2. Recrée proprement `backend\.venv` et `node_modules` pour CETTE machine.
3. Télécharge les modèles IA (`qwen2.5:7b`, `llava-phi3`, ~7,6 Go au total).

**Résultat attendu** : le message `INSTALLATION TERMINEE !` à la fin, sans `[ERREUR]`
ni `[X]` au-dessus.

> Si le script s'arrête après avoir installé Python ou Node.js pour la première
> fois, c'est normal — **fermez la fenêtre et relancez le script** (le `PATH` doit
> être rechargé).

---

## 2. Vérifier l'installation

Double-cliquez sur **`VERIFIER-INSTALLATION.bat`**.

**Résultat attendu** : uniquement des lignes `[OK]`. S'il y a des `[X]`, le script
indique la commande à lancer pour corriger — exécutez-la puis relancez la vérification.

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

## 4. Ouvrir l'accès depuis le réseau de la boutique

Par défaut, le pare-feu Windows peut bloquer les connexions entrantes depuis les
autres postes de la boutique. Ouvrez une invite PowerShell **administrateur** sur
le serveur et exécutez :

```powershell
New-NetFirewallRule -DisplayName "Marvin - Frontend" -Direction Inbound -LocalPort 3000 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "Marvin - Backend"  -Direction Inbound -LocalPort 8005 -Protocol TCP -Action Allow
```

**Résultat attendu** : depuis un autre poste de la boutique, `http://<IP-DU-SERVEUR>:3000`
s'ouvre correctement. Trouvez l'IP du serveur avec `ipconfig` (champ "Adresse IPv4").

---

## 5. Démarrage automatique après un redémarrage

Pour que Marvin reparte **tout seul** après un reboot ou une coupure de courant
(recommandé sur un serveur boutique), exécutez **en tant qu'administrateur** :

**`INSTALLER-DEMARRAGE-AUTO.bat`**

**Résultat attendu** : `[OK] Tâche planifiée créée`. Testez immédiatement sans
redémarrer avec la commande affichée à l'écran (`schtasks /run /tn "..."`), puis
vérifiez que `http://localhost:3000` répond une minute après.

> ℹ️ Cette tâche tourne sous le compte SYSTEM (aucune session utilisateur requise,
> démarre avant même l'écran de connexion). Contrepartie : les fonctionnalités qui
> ont besoin d'une session de bureau interactive (notifications visuelles Windows,
> presse-papiers) peuvent être indisponibles dans ce mode. Si vous en avez besoin au
> quotidien sur ce serveur, dites-le et on adaptera la tâche planifiée à un compte
> utilisateur dédié avec ouverture de session automatique.

---

## 6. Configuration propre à cette installation

- [ ] **Identité document** (auteur, organisation, logo, pied de page) : demandez
      directement à Marvin dans le chat, ou remplissez-la dans *Réglages → Connexions
      → Identité des documents*.
- [ ] **Comptes connectés** (Google Agenda/Gmail, Outlook, recherche web...) : à
      configurer dans *Réglages → Connexions*, propre à chaque déploiement — jamais
      copié d'une autre machine.
- [ ] **Ancien `data/`** (si migration depuis un autre poste) : copiez le dossier
      `data/` complet AVANT le premier démarrage pour récupérer réglages, compétences,
      mémoire et clé de compte de service Google.
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
