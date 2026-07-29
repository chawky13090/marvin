# Inventaire de sauvegarde des données Marvin

Date de référence : 2026-07-29
Version du contrat : 1.0

## Classes

| Classe | Contenu | Sauvegarde globale | Restauration |
|---|---|---|---|
| Autorité SQLite | `data/secretary.db` | snapshot SQLite cohérent | fichier restauré puis migrations et réconciliation |
| Registres durables | Truth Ledger, Mission OS, Forge, Arena, Model Market, Research Swarm | oui | contrôle SHA-256 avant extraction |
| Configuration et secrets | compétences, recettes, statistiques, coffre DPAPI | oui | même utilisateur Windows; secrets non portables |
| Artefacts utilisateur | documents, uploads, missions et workspaces de code, logos, webapps | oui | chemins relatifs validés, remplacement hors ligne à concevoir |
| Projections reconstructibles | Qdrant, Memory Mesh, cache reranker | non | régénération depuis SQLite et documents |
| Logs techniques | audit, incidents, HTTP, matching | non | politique de rotation propre |
| État machine/transitoire | VM Lab, validation, résultats Hyper-V, capacités détectées | non | redétection sur la machine cible |
| Sauvegardes | `data/backups` | jamais récursivement | cycle de rétention séparé |

Le manifeste exécutable vit dans `backend/full_backup.py`. Tout nouveau fichier ou dossier
de premier niveau sous `data/` doit être ajouté explicitement à une classe; sinon la création
du bundle échoue. Les fichiers `.lock`, `.tmp` et `.partial` ne sont jamais archivés.

## Format et garanties

- archive ZIP interne uniquement après copie en staging bornée ;
- maximum 20 000 fichiers, 512 Mio par fichier et 2 Gio de charge utile ;
- aucun lien symbolique, chemin absolu, composant `..` ou doublon ;
- manifeste versionné avec chemin, taille et SHA-256 de chaque fichier ;
- snapshot SQLite réalisé par l'API `sqlite3_backup`, puis `integrity_check` ;
- chiffrement intégral AES-256-GCM avec clé aléatoire enveloppée par DPAPI ;
- déchiffrement, vérification de chaque entrée et restauration dans une zone vide avant
  publication du point de récupération ;
- trois bundles globaux locaux conservés par défaut.

Le bundle est protégé au repos mais lié au compte Windows courant. Il ne constitue pas encore
une copie hors machine ou immuable. Une exportation portable devra utiliser une clé dérivée
d'une phrase secrète, un KDF standard audité et une procédure de récupération distincte.

La commande
`scripts/replicate-full-backup.py <bundle> <destination> --confirm-external-copy` copie le
bundle chiffré vers une racine existante hors de `data/`, relit son SHA-256 après publication,
écrit un sidecar JSON et conserve trois générations. Le résultat `same_volume` distingue une
simple copie logique d'une protection contre la panne physique. Cette réplication ne rend pas
portable le coffre DPAPI interne : elle protège le support, pas la perte du profil Windows.

## Exclusions justifiées

Qdrant et Memory Mesh sont des projections : les sauvegarder en parallèle de SQLite créerait
un point de cohérence supplémentaire et augmenterait inutilement le volume. Après récupération,
la réconciliation mémoire régénère ces projections. Les logs techniques ne sont pas des
preuves métier et suivent leur rétention. Les modèles Ollama, ISO et caches se retéléchargent
ou se redétectent.

## Application hors ligne et rollback

`scripts/restore-full-backup.py <bundle> --confirm-offline-restore` refuse de fonctionner
tant que le frontend ou le backend écoute. Il extrait et contrôle d'abord le bundle, crée un
nouveau point de retour global, remplace uniquement les autorités déclarées, conserve les
états machine et projections, puis réconcilie SQLite, Memory Mesh et Qdrant. Une erreur
restaure les anciennes autorités et réexécute la réconciliation. Un répertoire de rollback
n'est supprimé qu'après réussite ou compensation confirmée.

La création et la vérification restent isolées. Seule la commande hors ligne confirmée
remplace les données; son champ `pre_restore_filename` identifie le retour métier exact.
Rollback du code : réversion atomique du commit v2.462 puis du commit `20fcefe` si le format
global doit aussi disparaître. Les bundles `.mrvfull` restent des artefacts chiffrés
indépendants et peuvent être supprimés explicitement après conservation d'un autre point
vérifié.
