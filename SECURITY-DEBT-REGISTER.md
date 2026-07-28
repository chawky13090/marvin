# Marvin — Registre obligatoire de la dette de sécurité

Ce registre est un gate de livraison. Une dette de sécurité peut être ouverte pendant une
tranche progressive, mais elle ne peut être ni masquée, ni déclarée résolue sans preuve
reproductible. Toute évolution doit réévaluer son périmètre, ses entrées, ses sorties, ses
persistances, ses privilèges, son exposition réseau, ses secrets, ses logs et son rollback.

## États

- `OPEN` : risque confirmé, correction planifiée et priorisée.
- `MITIGATED` : réduction de risque livrée, traitement définitif restant.
- `VERIFIED` : correction testée, preuve et rollback documentés.
- `ACCEPTED` : exception explicite, datée, justifiée et approuvée par l'utilisateur. Aucune
  acceptation implicite ou permanente n'est autorisée.

## Registre actif au 2026-07-28

| ID | Sévérité | État | Périmètre | Constat et traitement obligatoire |
|---|---|---|---|---|
| SEC-001 | Critique | OPEN | API FastAPI | Le backend écoute sur toutes les interfaces et ne possède pas encore d'authentification applicative globale. Les origines LAN privées sont autorisées. Ajouter identité locale, jeton de session non exportable, autorisation serveur par capacité, protection WebSocket/SSE et mode LAN explicitement activé. |
| SEC-002 | Élevée | VERIFIED | Identifiants globaux | Les secrets globaux historiques sont migrés de SQLite vers DPAPI utilisateur, relus avant nettoyage, masqués dans l'API et couverts par corruption, concurrence et rollback. La base logique contient zéro secret global historique après migration v2.401. |
| SEC-003 | Élevée | VERIFIED | Comptes e-mail | La v2.422 migre mot de passe, jetons d'accès/rafraîchissement et secret client dans une enveloppe DPAPI distincte par compte. SQLite ne conserve que métadonnées et référence opaque. Migration, relecture avant nettoyage, multi-comptes, concurrence, formulaire vide, corruption, panne SQLite, panne coffre, suppression et rollback sont testés. Les trois comptes réels contiennent zéro champ secret logique et leurs connexions IMAP/SMTP réussissent 3/3 sans envoi. |
| SEC-004 | Élevée | VERIFIED | SSH | La v2.423 place mot de passe, clé privée et passphrase dans une enveloppe DPAPI par connexion; SQLite conserve une référence et des colonnes historiques vides. Migration, clé multi-ligne, concurrence, collision, mise à jour vide, suppression compensée, rollback, onze routes et transport sont testés. Les deux connexions réelles ont zéro secret SQLite et se résolvent; une cible valide `true`, l'autre expire au niveau réseau. Les erreurs HTTP/SSE/WebSocket/SFTP sont expurgées et l'audit ne conserve que leur classe. |
| SEC-005 | Élevée | VERIFIED | Sauvegardes | La v2.420 chiffre chaque snapshot par AES-256-GCM avec une clé aléatoire enveloppée par DPAPI utilisateur. Altération, mauvais contexte, concurrence, rotation, restauration compensée et migration réversible sont testés. La preuve réelle a migré 14 sauvegardes, restauré les 15 fichiers vers `.db`, les a rechiffrés puis restauré isolément le dernier avec contenu logique exact. La limitation de portabilité reste suivie séparément par SEC-012. |
| SEC-006 | Élevée | MITIGATED | SQLite actif | Les nouvelles connexions activent `secure_delete=ON`, `trusted_schema=OFF` et `cell_size_check=ON`. Exécuter hors ligne checkpoint, `VACUUM` et contrôle d'intégrité après migration de tous les secrets pour retirer les traces historiques du fichier actif et du WAL. |
| SEC-007 | Élevée | VERIFIED | OAuth historique | La v2.424 retire les deux services JavaScript qui écrivaient les jetons en clair et fait de FastAPI/DPAPI l'unique propriétaire OAuth. La migration copie et relit les anciens jetons avant nettoyage, préserve les identifiants autoritatifs existants et remplace la table par un tombstone de métadonnées. Migration Google/Microsoft, priorité, absence de clair dans le coffre, base neuve, callbacks obsolètes, confirmation et rollback exact sont testés. La base réelle est en schéma 6, sans colonne de jeton, avec zéro ligne, `quick_check=ok` et zéro violation FK. |
| SEC-008 | Élevée | OPEN | Compte de service Google | Aucun fichier de compte de service n'est présent actuellement. Le chemin d'upload persiste néanmoins une clé JSON en clair : appliquer chiffrement au repos, validation stricte, permissions minimales et suppression vérifiée. |
| SEC-009 | Élevée | OPEN | Données et ACL | Les ACL du dossier `data` n'ont pas encore un contrat installateur vérifié sur toutes les éditions Windows. Définir propriétaire, héritage, comptes autorisés et test de réparation sans casser le runtime ni la mise à jour. |
| SEC-010 | Moyenne | OPEN | Vérités, mémoire, preuves | Les registres métier peuvent contenir des données personnelles ou sensibles. Ajouter classification, durée de conservation, export et effacement sélectif avec preuve sans invalider silencieusement les chaînes d'intégrité. |
| SEC-011 | Moyenne | OPEN | Cycle de vie des secrets | Ajouter métadonnées non sensibles, date de création/rotation, révocation, expiration et alertes. Aucun secret ne doit apparaître dans les logs, erreurs, traces ou sorties de tests. |
| SEC-012 | Moyenne | OPEN | Portabilité | DPAPI utilisateur est volontairement lié au compte Windows et à la machine. L'installateur doit annoncer que les secrets ne migrent pas avec les données et conduire une réauthentification; un export chiffré optionnel exige une conception et une validation distinctes. |
| SEC-013 | Élevée | VERIFIED | Erreurs HTTP | Le handler global projetait le texte brut des exceptions au client et le persistait avec le traceback complet. La v2.402 retourne un identifiant d'incident opaque et journalise seulement classe, route, méthode et corrélation, sans message ni contenu de requête. |
| SEC-014 | Moyenne | VERIFIED | Intégrité relationnelle SQLite | La migration 5 archive intégralement chaque événement SSE sans parent avant retrait. Les 27 lignes réelles de deux tours correspondent bit à bit sur les champs métier au snapshot chiffré préalable; zéro violation FK reste. Les connexions vérifient désormais l'activation effective des clés étrangères et l'insertion SSE exige son parent indépendamment du pragma. Le chemin historique exact n'est pas démontrable après coup; la fenêtre correspond à un ancien processus du 22 juillet. Rollback de données explicite et restauration du snapshot sont documentés et testés. |
| SEC-015 | Élevée | VERIFIED | Dépendances frontend | La v2.426 met Next.js à niveau de 16.2.6 vers 16.2.12 pour les correctifs App Router/Turbopack et force `sharp` 0.35.3 afin de retirer les versions libvips vulnérables. `npm audit --omit=dev` retourne zéro vulnérabilité. Le build Turbopack, les contrats frontend, l'installateur et les parcours live empêchent une promotion non testée. |
| SEC-016 | Élevée | VERIFIED | Erreurs SSE durables | La v2.427 supprime le texte brut des exceptions du flux navigateur et de SQLite. Un incident opaque est retourné; seuls classe d'erreur, incident et condensat de requête rejoignent le journal technique. Les tests couvrent secret simulé, persistance, panne du logger et statut terminal invalide. |
| SEC-017 | Élevée | VERIFIED | Transport Ollama | La v2.428 empêche les erreurs déjà converties en événements SSE de contourner SEC-016. Corps HTTP, message brut, traceback, URL et modèle sont supprimés de la projection publique; catégories, statut HTTP sûr et incident opaque restent disponibles. |
| SEC-018 | Élevée | VERIFIED | Exécution des outils et MCP | La v2.429 remplace message, arguments et traceback d'une exception d'outil par un incident opaque et des métadonnées de forme. Les pannes de reçu, normalisation, exécution et audit sont expurgées et explicitement propagées. Le pont MCP masque ses exceptions et possède un test dédié dans le gate. |
| SEC-019 | Moyenne | VERIFIED | Provenance modèle et confidentialité | La v2.430 transporte et affiche fournisseur local/Cloud, mode de confidentialité, Cloud-only et classification sensible sur chaque sélection, y compris l'escalade de compétence. Les contrats prouvent la priorité Hyper local, l'absence de repli local en Ultra et le repli Agent cohérent en mode hybride. |
| SEC-020 | Élevée | VERIFIED | Cycle de vie mémoire et droit à l'oubli | La v2.431 coordonne SQLite, Memory Mesh et Qdrant pour créer, enrichir, consolider, expirer et oublier un souvenir. Une panne partielle est exposée sans faux succès, l'oubli global exige une confirmation, les souvenirs échus sont exclus du prompt, et un Mesh corrompu échoue fermé sans écrasement. |
| SEC-021 | Élevée | VERIFIED | Intégration et reprise Code Workspace | La v2.432 interdit d'appliquer un candidat avant acceptation de tous les gates, empêchant un fichier refusé de contaminer le worktree ou la tentative suivante. Le registre des jobs récupère sa dernière copie valide, échoue fermé si les deux copies sont corrompues et expurge les secrets usuels des diagnostics persistés et événements affichés. |
| SEC-022 | Moyenne | VERIFIED | Disponibilité LLM local et Hyper-V | La v2.433 supprime le préchauffage local en mode Cloud afin d'éviter l'épuisement RAM, sans désinstaller le repli confidentiel. Les runners Debian/Windows contrôlent la mémoire avant démarrage. Les smokes natifs prouvent checkpoints restaurés, secrets DPAPI, moindre privilège invité et politiques réseau sans modification de l'hôte. |
| SEC-023 | Élevée | VERIFIED | Boucle de réparation Code Workspace | Les diagnostics, check-ups et validations rejoignent le registre de preuves expurgé de la Coding Mission. Les contenus observés et documentations restent balisés non fiables, les sources sont limitées aux transports/domaines officiels du Radar, un candidat refusé reste hors du worktree, et seule la Definition of Done déterministe autorise la livraison. |

## Critère de fermeture

Une ligne passe à `VERIFIED` uniquement avec :

1. menace et frontière de confiance documentées ;
2. validation stricte des entrées et erreurs expurgées ;
3. test nominal, limites, panne, concurrence et non-régression selon le risque ;
4. preuve sur le runtime réel lorsque pertinent ;
5. migration montante idempotente ;
6. rollback testé et ordre opératoire documenté ;
7. journalisation structurée sans donnée sensible ;
8. mise à jour du journal de développement et commit atomique.
