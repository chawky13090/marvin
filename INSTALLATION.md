# Installation Windows en un clic

Cible technique : Windows 10/11 x64 ou Windows Server 2019/2022/2025 avec interface graphique

Versions : Marvin 2.653.0, Python 3.13.15, Node.js 24.19.0 LTS, Ollama 0.32.11

Niveau requis : utilisateur Windows standard; administrateur seulement pour les fonctions système optionnelles

Impact de production : faible; arrêt contrôlé lors d'une mise à niveau

Fenêtre de maintenance : 20 à 90 minutes selon Internet, matériel et modèles sélectionnés

Privilèges requis : aucun pour le socle

Sauvegarde préalable : données préservées automatiquement lors d'une mise à niveau

Plan de rollback : restauration automatique du code précédent si l'installation échoue

## Résultat attendu

Le destinataire reçoit un ZIP propre, l'extrait et double-clique sur `INSTALLER-MARVIN.bat`.
L'installation se poursuit dans la même exécution, sans demander de relancer la fenêtre après
Python ou Node.js. Marvin est installé par défaut dans `%LOCALAPPDATA%\Programs\Marvin`.

Le socle ne dépend pas de Docker, Hyper-V, Windows Sandbox, d'un GPU ou d'une API payante.
Chaque composant optionnel est publié comme `available`, `degraded` ou `unavailable` dans
`data\install-capabilities.json`. Une absence optionnelle ne devient jamais un faux succès.

## Prérequis du poste cible

- Windows x64 build 17763 ou ultérieur;
- connexion HTTPS sortante vers python.org, nodejs.org, github.com et ollama.com;
- au moins 40 Gio libres;
- PowerShell 5.1 ou PowerShell 7;
- aucun secret ni ancien dossier `data` nécessaire pour une installation neuve.

Les versions téléchargées et leurs SHA-256 sont épinglés dans
`scripts\windows-install-components.json`. Python est en plus contrôlé par signature
Authenticode. Les archives ZIP sont refusées en cas de traversée de chemin.

## 1. Construire le paquet propre

Sur le poste de développement, double-cliquer sur :

```text
CREER-PAQUET-MARVIN.bat
```

Le constructeur exige un worktree Git suivi propre et utilise `git archive HEAD`. Il ne peut
donc pas embarquer `data`, `.env.local`, `.venv`, `node_modules`, `.next`, caches, captures ou
fichiers non suivis. Deux fichiers sont créés :

```text
dist\Marvin-Windows-v2.653.0.zip
dist\Marvin-Windows-v2.653.0.zip.sha256
```

## 2. Transférer et vérifier

Copier les deux fichiers sur le poste cible. La vérification manuelle du ZIP est recommandée :

```text
# Target: Windows 10/11 ou Windows Server 2019+
# Shell/CLI: PowerShell 5.1+
# Privileges: Utilisateur
# Objective: vérifier l'intégrité du paquet avant extraction

$zip = '.\Marvin-Windows-v2.653.0.zip'
Get-FileHash -LiteralPath $zip -Algorithm SHA256
Get-Content -LiteralPath ($zip + '.sha256')
```

Les deux empreintes doivent être identiques. Le bootstrap vérifie ensuite une seconde fois le
SHA-256 du payload interne avant toute publication dans la cible.

## 3. Installer

1. Extraire entièrement le ZIP dans un dossier local.
2. Ouvrir le dossier `Marvin-Windows-v2.653.0` extrait.
3. Double-cliquer sur `INSTALLER-MARVIN.bat`.
4. Laisser la fenêtre ouverte jusqu'à `INSTALLATION TERMINEE`.

L'installeur réalise chronologiquement :

1. contrôle Windows, architecture, disque et mutex d'installation;
2. vérification du paquet et publication atomique du code;
3. sélection d'un Python/Node/Ollama système compatible ou installation locale d'une version
   gérée et épinglée;
4. recréation de `backend\.venv` et `node_modules` depuis les fichiers de verrouillage;
5. contrôle des dépendances Python, Next.js et Sharp;
6. création et durcissement ACL de `data`;
7. détection matérielle, choix dynamique des modèles, qualification et calibration du contexte;
8. tentative bornée de LibreOffice et, si Docker existe, de SearXNG local épinglé;
9. build de production, raccourcis, rapport de capacités;
10. démarrage et contrôle HTTP du backend, des 364 outils et du frontend.

Les téléchargements sont repris par relance du même fichier après un incident. Ils sont
conservés pendant un échec, puis supprimés après réussite. Aucun modèle local fixe n'est imposé :
le portefeuille est choisi selon CPU, RAM, VRAM et métadonnées du modèle. Aucun `num_ctx` n'est
envoyé à un modèle Cloud.

## 4. Vérifier et diagnostiquer

Double-cliquer sur `VERIFIER-INSTALLATION.bat`. Les fichiers de diagnostic sont :

| Composant | Chemin | Contenu | Rétention |
|---|---|---|---|
| État de l'installation | `runtime\install\state.json` | étapes, durées, erreurs, empreintes de téléchargement | remplacé à chaque installation |
| Journal structuré | `runtime\install\install.log.jsonl` | événements sans secret, corrélés par installation | rotation à 2 Mio, 5 archives |
| Capacités | `data\install-capabilities.json` | disponible/dégradé/indisponible et remédiation | dernière détection |
| Profil Ollama | `data\install\ollama-context-profile.json` | contexte local réellement qualifié | recalibré si matériel/modèle change |

Résultats obligatoires : backend `status=ok`, version 2.653.0, 364 outils, frontend HTTP 200.
Docker/SearXNG, LibreOffice, Hyper-V et Sandbox peuvent être dégradés sans bloquer le socle.

## 5. Mise à niveau et reprise

Relancer l'installateur d'un nouveau paquet. Avant de remplacer le code, le bootstrap arrête
Marvin et conserve l'installation précédente sous `Marvin.rollback-<date>`. Il transfère
atomiquement `data`, `runtime` et `.env.local` dans le nouveau code. Si une étape obligatoire
échoue, il restaure l'installation précédente. Une étape optionnelle échouée reste déclarée
`degraded` et n'annule pas le socle.

## 6. Désinstallation et rollback

Double-cliquer sur `DESINSTALLER-MARVIN.bat`. Par défaut :

- Marvin est arrêté;
- raccourcis et intégrations créés par Marvin sont retirés;
- les runtimes système partagés ne sont jamais supprimés;
- les données sont déplacées vers `%LOCALAPPDATA%\Marvin\PreservedData`.

La suppression des données exige le paramètre PowerShell explicite `-RemoveData`. Le script
refuse toute racine sans marqueur d'installation Marvin et toute cible dangereusement large.

Pour un rollback de code après une mise à niveau réussie, arrêter Marvin, renommer la cible
courante, puis remettre le dossier `Marvin.rollback-<date>` au nom `Marvin`. Les données et le
runtime étant préservés lors de la mise à niveau, aucune migration descendante n'est requise
pour cette version.

## Limites connues

- L'installation complète exige Internet au premier passage; le paquet ne transporte pas les
  modèles ni les dépendances tierces volumineuses.
- Les secrets DPAPI d'un autre compte Windows ne sont pas portables; les connexions OAuth et
  coffres doivent être recréés sous le nouvel utilisateur.
- Docker Desktop, Hyper-V et Windows Sandbox peuvent exiger élévation, édition Windows adaptée
  et redémarrage. L'installeur du socle ne les active jamais silencieusement.
- Une preuve de reprise après perte physique de l'hôte exige toujours une sauvegarde sur un
  support physiquement distinct; une VM du même disque ne ferme pas ce risque.
