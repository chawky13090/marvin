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

## Registre actif au 2026-08-02

| ID | Sévérité | État historique déclaré | Périmètre | Constat et traitement obligatoire |
|---|---|---|---|---|
| SEC-001 | Critique | MITIGATED | API FastAPI et Next.js | Les v2.465–2.466 imposent session HMAC, CSRF et capacités; v2.480–2.481 isolent les listeners locaux derrière Caddy. La v2.579 valide réellement le service Windows automatique sous `LocalService`, TCP/443, pare-feu Domaine/Privé, confiance par empreinte, journal borné, cycle arrêt/redémarrage et rollback désinstallation/réinstallation. Windows exige volontairement une confirmation système pour retirer une racine; le ciblage exact a été observé sans suppression acceptée. Les parcours de confiance/révocation Android, iOS, macOS et Linux restent à automatiser avant `VERIFIED`. |
| SEC-002 | Élevée | VERIFIED | Identifiants globaux | Les secrets globaux historiques sont migrés de SQLite vers DPAPI utilisateur, relus avant nettoyage, masqués dans l'API et couverts par corruption, concurrence et rollback. La base logique contient zéro secret global historique après migration v2.401. |
| SEC-003 | Élevée | VERIFIED | Comptes e-mail | La v2.422 migre mot de passe, jetons d'accès/rafraîchissement et secret client dans une enveloppe DPAPI distincte par compte. SQLite ne conserve que métadonnées et référence opaque. Migration, relecture avant nettoyage, multi-comptes, concurrence, formulaire vide, corruption, panne SQLite, panne coffre, suppression et rollback sont testés. Les trois comptes réels contiennent zéro champ secret logique et leurs connexions IMAP/SMTP réussissent 3/3 sans envoi. |
| SEC-004 | Élevée | VERIFIED | SSH | La v2.423 place mot de passe, clé privée et passphrase dans une enveloppe DPAPI par connexion; SQLite conserve une référence et des colonnes historiques vides. Migration, clé multi-ligne, concurrence, collision, mise à jour vide, suppression compensée, rollback, onze routes et transport sont testés. Les deux connexions réelles ont zéro secret SQLite et se résolvent; une cible valide `true`, l'autre expire au niveau réseau. Les erreurs HTTP/SSE/WebSocket/SFTP sont expurgées et l'audit ne conserve que leur classe. |
| SEC-005 | Élevée | VERIFIED | Sauvegardes | La v2.420 chiffre chaque snapshot par AES-256-GCM avec une clé aléatoire enveloppée par DPAPI utilisateur. Altération, mauvais contexte, concurrence, rotation, restauration compensée et migration réversible sont testés. La preuve réelle a migré 14 sauvegardes, restauré les 15 fichiers vers `.db`, les a rechiffrés puis restauré isolément le dernier avec contenu logique exact. La limitation de portabilité reste suivie séparément par SEC-012. |
| SEC-006 | Élevée | VERIFIED | SQLite actif | La v2.581 impose une maintenance hors ligne sérialisée : espace disque, sauvegarde DPAPI relue, checkpoint WAL, intégrité complète/FK, `VACUUM`, second checkpoint et validation finale. Une panne post-sauvegarde restaure automatiquement. Le rollback réel a restauré les 410 947 584 octets d'origine, puis la maintenance finale a stabilisé la base à 408 416 256 octets, WAL vide, intégrité et FK OK. Les rapports sont atomiques, inclus dans le bundle global et bornés à 365 jours/32 fichiers. |
| SEC-007 | Élevée | VERIFIED | OAuth historique | La v2.424 retire les deux services JavaScript qui écrivaient les jetons en clair et fait de FastAPI/DPAPI l'unique propriétaire OAuth. La migration copie et relit les anciens jetons avant nettoyage, préserve les identifiants autoritatifs existants et remplace la table par un tombstone de métadonnées. Migration Google/Microsoft, priorité, absence de clair dans le coffre, base neuve, callbacks obsolètes, confirmation et rollback exact sont testés. La base réelle est en schéma 6, sans colonne de jeton, avec zéro ligne, `quick_check=ok` et zéro violation FK. |
| SEC-008 | Élevée | VERIFIED | Compte de service Google | La v2.580 valide strictement le JSON, le point OAuth, l'identité et RSA >= 2048 bits, puis stocke le contenu canonique sous DPAPI utilisateur. Calendar ne lit plus de clé privée sur disque. La migration réelle, la relecture avant effacement, l'absence finale de JSON clair, le rollback à ACL utilisateur+SYSTEM et la remigration ont été vérifiés. Upload borné, corruption, panne du coffre, divergence entre copies et suppression compensée sont couverts. |
| SEC-009 | Élevée | VERIFIED | Données et ACL | La v2.582 limite récursivement `data` à l'utilisateur courant, SYSTEM et Administrateurs. Le contrat refuse reparse points et ACL explicites incompatibles, contrôle tous les descendants, sauvegarde DACL/empreinte/SDDL parent, refuse un snapshot altéré et restaure par héritage uniquement si le parent est inchangé. Sur 2 244 éléments réels, trois grants supplémentaires ont été retirés; rollback réel, réapplication, idempotence et intégration installateur ont été validés. |
| SEC-010 | Moyenne | MITIGATED | Vérités, mémoire, preuves | Les v2.586–2.587 classifient 14 flux et exportent exactement huit registres racine sous chiffrement vérifié. La v2.588 ajoute l'effacement hors ligne confirmé : snapshot chiffré, contrôle de concurrence, réécriture/rechaînage atomique, compensation locale et restauration retrouvant l'empreinte initiale. Le reçu exclut valeur et contenu. Reste avant `VERIFIED` : politique testée de finalisation/expiration du rollback qui contient temporairement les données effacées, puis intégration UX. |
| SEC-011 | Moyenne | VERIFIED | Cycle de vie des secrets | La v2.583 ajoute un registre compagnon non sensible, atomique et borné pour création, rotation, révision, révocation, expiration, catégorie et échéance de revue. Expiration et corruption échouent fermées; Doctor alerte sans exposer clé ou valeur. L'audit conserve uniquement catégorie et révision. Création, rotation, expiration, révocation, corruption, migration historique, compensation et absence de secret dans les logs sont testées. |
| SEC-012 | Moyenne | VERIFIED | Portabilité | La v2.583 maintient DPAPI `CurrentUser` plutôt qu'un export affaibli. L'installateur annonce la dépendance au compte Windows et son rapport vérifie chaque ciphertext sans le restituer. Un coffre illisible devient `reauthentication_required` et conduit à reconnecter les comptes et réenregistrer les identifiants. Le runtime réel compte 10 secrets lisibles et zéro illisible; la simulation de coffre non déchiffrable produit le repli attendu. |
| SEC-013 | Élevée | VERIFIED | Erreurs HTTP | Le handler global projetait le texte brut des exceptions au client et le persistait avec le traceback complet. La v2.402 retourne un identifiant d'incident opaque et journalise seulement classe, route, méthode et corrélation, sans message ni contenu de requête. |
| SEC-014 | Moyenne | VERIFIED | Intégrité relationnelle SQLite | La migration 5 archive intégralement chaque événement SSE sans parent avant retrait. Les 27 lignes réelles de deux tours correspondent bit à bit sur les champs métier au snapshot chiffré préalable; zéro violation FK reste. Les connexions vérifient désormais l'activation effective des clés étrangères et l'insertion SSE exige son parent indépendamment du pragma. Le chemin historique exact n'est pas démontrable après coup; la fenêtre correspond à un ancien processus du 22 juillet. Rollback de données explicite et restauration du snapshot sont documentés et testés. |
| SEC-015 | Élevée | VERIFIED | Dépendances frontend | La v2.426 met Next.js à niveau de 16.2.6 vers 16.2.12 pour les correctifs App Router/Turbopack et force `sharp` 0.35.3 afin de retirer les versions libvips vulnérables. `npm audit --omit=dev` retourne zéro vulnérabilité. Le build Turbopack, les contrats frontend, l'installateur et les parcours live empêchent une promotion non testée. |
| SEC-016 | Élevée | VERIFIED | Erreurs SSE durables | La v2.427 supprime le texte brut des exceptions du flux navigateur et de SQLite. Un incident opaque est retourné; seuls classe d'erreur, incident et condensat de requête rejoignent le journal technique. Les tests couvrent secret simulé, persistance, panne du logger et statut terminal invalide. |
| SEC-017 | Élevée | VERIFIED | Transport Ollama | La v2.428 empêche les erreurs déjà converties en événements SSE de contourner SEC-016. Corps HTTP, message brut, traceback, URL et modèle sont supprimés de la projection publique; catégories, statut HTTP sûr et incident opaque restent disponibles. |
| SEC-018 | Élevée | VERIFIED | Exécution des outils et MCP | La v2.429 remplace message, arguments et traceback d'une exception d'outil par un incident opaque et des métadonnées de forme. Les pannes de reçu, normalisation, exécution et audit sont expurgées et explicitement propagées. Le pont MCP masque ses exceptions et possède un test dédié dans le gate. |
| SEC-019 | Moyenne | VERIFIED | Provenance modèle et confidentialité | La v2.430 transporte et affiche fournisseur local/Cloud, mode de confidentialité, Cloud-only et classification sensible sur chaque sélection. La v2.458 remplace les quatre préfixes historiques par une liste positive de sorties publiques et classe les 344 outils ainsi que toute nouveauté comme privés par défaut. Les contrats prouvent la priorité Hyper local, l'absence de repli local en Ultra, le repli hybride avant réinjection et la détection de valeurs sensibles structurées. |
| SEC-020 | Élevée | VERIFIED | Cycle de vie mémoire et droit à l'oubli | La v2.431 coordonne SQLite, Memory Mesh et Qdrant pour créer, enrichir, consolider, expirer et oublier un souvenir. Une panne partielle est exposée sans faux succès, l'oubli global exige une confirmation, les souvenirs échus sont exclus du prompt, et un Mesh corrompu échoue fermé sans écrasement. |
| SEC-021 | Élevée | VERIFIED | Intégration et reprise Code Workspace | La v2.432 interdit d'appliquer un candidat avant acceptation de tous les gates, empêchant un fichier refusé de contaminer le worktree ou la tentative suivante. Le registre des jobs récupère sa dernière copie valide, échoue fermé si les deux copies sont corrompues et expurge les secrets usuels des diagnostics persistés et événements affichés. |
| SEC-022 | Moyenne | VERIFIED | Disponibilité LLM local et Hyper-V | La v2.433 supprime le préchauffage local en mode Cloud afin d'éviter l'épuisement RAM, sans désinstaller le repli confidentiel. Les runners Debian/Windows contrôlent la mémoire avant démarrage. Les smokes natifs prouvent checkpoints restaurés, secrets DPAPI, moindre privilège invité et politiques réseau sans modification de l'hôte. |
| SEC-023 | Élevée | VERIFIED | Boucle de réparation Code Workspace | Les diagnostics, check-ups et validations rejoignent le registre de preuves expurgé de la Coding Mission. Les contenus observés et documentations restent balisés non fiables, les sources sont limitées aux transports/domaines officiels du Radar, un candidat refusé reste hors du worktree, et seule la Definition of Done déterministe autorise la livraison. |
| SEC-024 | Élevée | MITIGATED | Sauvegarde globale | Les v2.461–2.463 couvrent bundle local DPAPI, restauration compensée et réplication vérifiée. La v2.584 ajoute un format portable AES-256-GCM/scrypt excluant explicitement les secrets DPAPI et démontre un aller-retour réel de 1 733 fichiers/618 281 759 octets. L'inventaire réel est fermé et distingue autorités, caches et état machine. Restent avant `VERIFIED` : copie puis restauration sur stockage physiquement distinct ou immuable, application contrôlée sur un second poste et intégration UX/installateur. |

## Réévaluation machine au 2026-08-12

Cette table ne réécrit pas l'historique. `UNKNOWN` signifie que l'état historique n'a pas
encore satisfait le contrat de preuve v1, pas que la sécurité du produit a régressé. Une
promotion à `VERIFIED` exige un commit et des tests existants, un rollback non vide et, pour
les sévérités Critique ou Élevée, un artefact de preuve runtime existant. Une validation
runtime dangereuse reste `UNKNOWN` jusqu'à son exécution dans un environnement isolé.

| ID | État réévalué | Motif calculable | Commit | Tests nommés | Rollback | Preuve runtime |
|---|---|---|---|---|---|---|
| SEC-001 | MITIGATED | traitement_multi_plateforme_incomplet | — | — | — | — |
| SEC-002 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-003 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-004 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-005 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-006 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-007 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-008 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-009 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-010 | MITIGATED | expiration_rollback_et_ux_incompletes | — | — | — | — |
| SEC-011 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-012 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-013 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-014 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-015 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-016 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-017 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-018 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-019 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-020 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-021 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-022 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-023 | UNKNOWN | attestation_machine_v1_en_attente | — | — | — | — |
| SEC-024 | MITIGATED | restauration_hors_machine_incomplete | — | — | — | — |

Résumé dérivé : `SECURITY_REGISTER_SUMMARY: VERIFIED=0; MITIGATED=3; UNKNOWN=21; OPEN=0; ACCEPTED=0`.

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
