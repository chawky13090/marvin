# Installation Windows en un clic

Cible technique : socle Windows x64 build 17763+; profil Full à qualifier sur une édition compatible Docker Desktop

Versions épinglées : Marvin 2.697.0, Python 3.13.15, Node.js 24.19.0, Ollama 0.32.11, Docker Desktop 4.94.0, LibreOffice 26.2.5.2

Niveau requis : utilisateur Windows standard; administrateur pour les composants système exigés par Full

Impact de production : faible; arrêt contrôlé lors d'une mise à niveau

Fenêtre de maintenance : 20 à 90 minutes selon Internet, matériel et modèles sélectionnés

Privilèges requis : aucun pour Core; élévation limitée aux installations système dans Full

Sauvegarde préalable : données préservées automatiquement lors d'une mise à niveau

Plan de rollback : restauration du code précédent si une étape obligatoire échoue; conservation du nouveau code si un redémarrage est requis

## Résultat attendu

Le destinataire reçoit un EXE signé privé ou un ZIP propre. L'EXE embarque le ZIP
et vérifie son SHA-256 avant extraction; le ZIP se lance par `INSTALLER-MARVIN.bat`.
L'installation se poursuit dans la même exécution, sans demander de relancer la fenêtre après
Python ou Node.js. Marvin est installé par défaut dans `%LOCALAPPDATA%\Programs\Marvin`.

Le profil `Full`, par défaut, exige Docker/SearXNG et LibreOffice. Le profil `Core`,
choisi explicitement, conserve un socle sans Docker et signale les capacités absentes.
Hyper-V n'est pas obligatoire si WSL 2 fournit la virtualisation nécessaire à Docker.
Windows Sandbox, GPU et API Cloud ne sont pas nécessaires au socle.
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
PREPARER-PAQUET-BOUTIQUE.bat
```

Le constructeur exige un worktree Git suivi propre et utilise `git archive HEAD`. Il ne peut
donc pas embarquer `data`, `.env.local`, `.venv`, `node_modules`, `.next`, caches, captures ou
fichiers non suivis. Les fichiers versionnés produits comprennent :

```text
dist\Marvin-Windows-v2.697.0.zip
dist\Marvin-Windows-v2.697.0.zip.sha256
dist\Marvin-Setup-Private-v2.697.0.exe
dist\Marvin-Setup-Private-v2.697.0.exe.sha256
```

## 2. Transférer et vérifier

Pour le ZIP, copier le ZIP et son empreinte. Pour l'EXE, copier l'EXE et son empreinte;
la chaîne privée exige en plus les deux certificats publics, leurs sidecars SHA-256,
`trust-marvin-private-publisher.ps1`, `FAIRE-CONFIANCE-A-MARVIN.bat` et
`RETIRER-CONFIANCE-MARVIN.bat` dans le même dossier. Vérifier les empreintes par
un canal de confiance distinct avant l'import. La confiance privée s'importe explicitement
avec UAC sur un poste contrôlé par le propriétaire; elle n'est ni publique Microsoft ni
une garantie de réputation SmartScreen. Les clés privées et PFX ne sont jamais transférés.

La vérification manuelle du ZIP est recommandée :

```text
# Target: Windows 10/11 ou Windows Server 2019+
# Shell/CLI: PowerShell 5.1+
# Privileges: Utilisateur
# Objective: vérifier l'intégrité du paquet avant extraction

$zip = '.\Marvin-Windows-v2.697.0.zip'
Get-FileHash -LiteralPath $zip -Algorithm SHA256
Get-Content -LiteralPath ($zip + '.sha256')
```

Les deux empreintes doivent être identiques. Le bootstrap vérifie ensuite une seconde fois le
SHA-256 du payload interne avant toute publication dans la cible.

## 3. Installer

1. Extraire entièrement le ZIP dans un dossier local.
2. Ouvrir le dossier `Marvin-Windows-v2.697.0` extrait.
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
8. qualification obligatoire de Docker/SearXNG et LibreOffice dans Full, avec
   licence Docker explicitement acceptée; dans Core, capacités optionnelles déclarées;
9. build de production, raccourcis, rapport de capacités;
10. démarrage et contrôle HTTP du backend, des 364 outils et du frontend.

Les téléchargements sont repris par relance du même fichier après un incident. Ils sont
conservés pendant un échec, puis supprimés après réussite. Aucun modèle local fixe n'est imposé :
le portefeuille est choisi selon CPU, RAM, VRAM et métadonnées du modèle. Aucun `num_ctx` n'est
envoyé à un modèle Cloud.

### Activer Ollama Cloud sur le poste cible

L'identité Cloud n'est jamais copiée depuis le poste de développement et aucun identifiant,
cookie ou jeton n'est inclus dans le ZIP. Après l'installation, l'utilisateur du poste cible
ouvre un PowerShell sous son propre compte et exécute :

```text
# Target: Windows 10/11 ou Windows Server 2019+
# Shell/CLI: PowerShell 5.1+
# Privileges: Utilisateur
# Objective: associer l'instance Ollama locale au compte Ollama Cloud du propriétaire

ollama signin
```

L'authentification se termine dans le navigateur. Marvin utilise ensuite la session Ollama
locale; il ne reçoit ni ne stocke le mot de passe Ollama. Une VM de qualification sans identité
doit publier le Cloud comme non évalué par conception, et non comme indisponible. Les modèles
Cloud ne reçoivent aucun `num_ctx` client afin de conserver la capacité maximale du fournisseur.

## 4. Vérifier et diagnostiquer

Double-cliquer sur `VERIFIER-INSTALLATION.bat`. Les fichiers de diagnostic sont :

| Composant | Chemin | Contenu | Rétention |
|---|---|---|---|
| État de l'installation | `runtime\install\state.json` | étapes, durées, erreurs, empreintes de téléchargement | remplacé à chaque installation |
| Journal structuré | `runtime\install\install.log.jsonl` | événements sans secret, corrélés par installation | rotation à 2 Mio, 5 archives |
| Capacités | `data\install-capabilities.json` | disponible/dégradé/indisponible et remédiation | dernière détection |
| Profil Ollama | `data\install\ollama-context-profile.json` | contexte local réellement qualifié | recalibré si matériel/modèle change |

Résultats du socle : backend `status=ok`, version 2.697.0, 364 outils, frontend HTTP 200.
Full exige en plus Docker/SearXNG et LibreOffice qualifiés. Un agent local non qualifié
ou une identité Cloud absente ne constitue pas une preuve de chat IA opérationnel.
Les tests doivent distinguer installation, interface et réussite d'une demande IA réelle.

## 5. Mise à niveau et reprise

Relancer l'installateur d'un nouveau paquet. Avant de remplacer le code, le bootstrap arrête
Marvin et conserve l'installation précédente sous `Marvin.rollback-<date>`. Il transfère
atomiquement `data`, `runtime` et `.env.local` dans le nouveau code. Si une étape obligatoire
échoue, il restaure l'installation précédente. Une étape optionnelle échouée reste déclarée
`degraded` et n'annule pas le socle. Le code 3010 signifie redémarrage requis : le code
nouveau est conservé, la reprise HKCU RunOnce pointe vers ce code et se lance à la
prochaine ouverture de session. Ne pas déplacer ou restaurer la cible pendant cette attente.

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
runtime étant préservés lors de la mise à niveau, ils ne sont pas automatiquement remis
à leur état antérieur. Si la version change un schéma ou une configuration persistante,
appliquer aussi sa procédure de descente documentée ou une sauvegarde vérifiée.

## Limites connues

- v2.696 a été qualifiée en mise à niveau signée sur Windows 11 Pro x64 avec
  prérequis système présents; ce n'est pas une certification de tous les Windows.
  Le test v2.697 sur une nouvelle cible Core est un parcours distinct, sans UAC,
  Docker Desktop interactif ni authentification Cloud. Aucun de ces résultats
  ne permet d'annoncer une installation Full sur Windows vierge entièrement prouvée.

- L'installation complète exige Internet au premier passage; le paquet ne transporte pas les
  modèles ni les dépendances tierces volumineuses.
- Les secrets DPAPI d'un autre compte Windows ne sont pas portables; les connexions OAuth et
  coffres doivent être recréés sous le nouvel utilisateur.
- Docker Desktop, Hyper-V et Windows Sandbox peuvent exiger élévation, édition Windows adaptée
  et redémarrage. L'installeur du socle ne les active jamais silencieusement.
- Une preuve de reprise après perte physique de l'hôte exige toujours une sauvegarde sur un
  support physiquement distinct; une VM du même disque ne ferme pas ce risque.
