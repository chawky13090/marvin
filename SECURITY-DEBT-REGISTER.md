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
| SEC-003 | Élevée | OPEN | Comptes e-mail | Trois comptes conservent encore mots de passe ou jetons dans le JSON SQLite. Migrer chaque champ sensible vers le coffre commun, conserver uniquement les métadonnées et tester OAuth, IMAP, SMTP, suppression et reprise. |
| SEC-004 | Élevée | OPEN | SSH | Deux connexions conservent encore mot de passe, clé privée ou passphrase dans SQLite. Migrer vers le coffre commun avec mise à jour transactionnelle et compatibilité des appels existants. |
| SEC-005 | Élevée | VERIFIED | Sauvegardes | La v2.420 chiffre chaque snapshot par AES-256-GCM avec une clé aléatoire enveloppée par DPAPI utilisateur. Altération, mauvais contexte, concurrence, rotation, restauration compensée et migration réversible sont testés. La preuve réelle a migré 14 sauvegardes, restauré les 15 fichiers vers `.db`, les a rechiffrés puis restauré isolément le dernier avec contenu logique exact. La limitation de portabilité reste suivie séparément par SEC-012. |
| SEC-006 | Élevée | MITIGATED | SQLite actif | Les nouvelles connexions activent `secure_delete=ON`, `trusted_schema=OFF` et `cell_size_check=ON`. Exécuter hors ligne checkpoint, `VACUUM` et contrôle d'intégrité après migration de tous les secrets pour retirer les traces historiques du fichier actif et du WAL. |
| SEC-007 | Élevée | OPEN | OAuth historique | La table `oauth_tokens` est vide sur cette installation, mais son schéma accepte des jetons en clair. Supprimer son usage résiduel ou migrer ses futurs jetons vers le coffre avant de considérer le domaine OAuth consolidé. |
| SEC-008 | Élevée | OPEN | Compte de service Google | Aucun fichier de compte de service n'est présent actuellement. Le chemin d'upload persiste néanmoins une clé JSON en clair : appliquer chiffrement au repos, validation stricte, permissions minimales et suppression vérifiée. |
| SEC-009 | Élevée | OPEN | Données et ACL | Les ACL du dossier `data` n'ont pas encore un contrat installateur vérifié sur toutes les éditions Windows. Définir propriétaire, héritage, comptes autorisés et test de réparation sans casser le runtime ni la mise à jour. |
| SEC-010 | Moyenne | OPEN | Vérités, mémoire, preuves | Les registres métier peuvent contenir des données personnelles ou sensibles. Ajouter classification, durée de conservation, export et effacement sélectif avec preuve sans invalider silencieusement les chaînes d'intégrité. |
| SEC-011 | Moyenne | OPEN | Cycle de vie des secrets | Ajouter métadonnées non sensibles, date de création/rotation, révocation, expiration et alertes. Aucun secret ne doit apparaître dans les logs, erreurs, traces ou sorties de tests. |
| SEC-012 | Moyenne | OPEN | Portabilité | DPAPI utilisateur est volontairement lié au compte Windows et à la machine. L'installateur doit annoncer que les secrets ne migrent pas avec les données et conduire une réauthentification; un export chiffré optionnel exige une conception et une validation distinctes. |
| SEC-013 | Élevée | VERIFIED | Erreurs HTTP | Le handler global projetait le texte brut des exceptions au client et le persistait avec le traceback complet. La v2.402 retourne un identifiant d'incident opaque et journalise seulement classe, route, méthode et corrélation, sans message ni contenu de requête. |
| SEC-014 | Moyenne | OPEN | Intégrité relationnelle SQLite | Le contrôle réel v2.419 détecte 27 événements SSE historiques orphelins dans `chat_turn_events`; `quick_check` reste sain et les sauvegardes signalent désormais ce nombre sans masquer ni bloquer la reprise. Ajouter une migration montante qui archive puis retire uniquement les orphelins sans parent, une migration descendante de restauration, identifier l'ancien chemin ayant écrit avec les clés étrangères désactivées et prouver que le défaut ne réapparaît pas. |

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
