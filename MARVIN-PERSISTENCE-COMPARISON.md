# Comparatif de persistance Marvin

Date de référence : 2026-07-29  
Version : 2.470.0  
Périmètre : poste Windows local, installation simple, fonctionnement hors ligne, secrets
DPAPI, missions longues, preuves durables et recherche sémantique.

## Conclusion

La migration globale vers LangGraph, Mastra ou PostgreSQL n'est pas justifiée aujourd'hui.
Marvin doit conserver :

1. **SQLite WAL** comme source autoritative métier et transactionnelle ;
2. **Qdrant local** comme projection vectorielle reconstructible ;
3. les **registres append-only chaînés** comme preuves métier ;
4. les snapshots atomiques actuels pour les missions longues.

Le gain pertinent de LangGraph et Mastra n'est pas leur base de données : c'est leur contrat
explicite de checkpoints, threads/runs, reprise et historique. Marvin doit reprendre ce
principe derrière une interface interne, sans importer un second orchestrateur ni déplacer
ses 51 tables. PostgreSQL devient une cible optionnelle seulement pour un futur mode
multi-utilisateur ou multi-instance. Qdrant serveur devient une cible optionnelle lorsque
les snapshots natifs, la réplication ou un volume vectoriel important sont requis.

## Faits mesurés sur cette installation

`scripts/benchmark_persistence.py` n'affiche aucun contenu métier et ne modifie pas la base
réelle. Le 29 juillet 2026, avec Python et SQLite 3.50.4 :

| Mesure | Résultat |
|---|---:|
| Base SQLite | 75 182 080 octets |
| Tables métier/techniques | 51 |
| Mode de journal | WAL |
| Clés étrangères | actives |
| `PRAGMA quick_check` | `ok` |
| Lecture du schéma, p50 / p95 sur 500 passes | 0,1045 / 0,1652 ms |
| Écritures synthétiques, 4 writers, 400 transactions | 325,64 transactions/s |
| Intégrité après concurrence synthétique | `ok` |

Ce benchmark établit une baseline Marvin, pas une comparaison de performance avec des
produits non installés. Il doit être rejoué sur les futures machines et avant toute migration.

## Comparaison

| Option | Apport réel | Sécurité et résilience | Coût/complexité | Décision Marvin |
|---|---|---|---|---|
| SQLite WAL actuel | Transactions ACID, fichier portable, sauvegarde déjà vérifiée | DPAPI, FK, WAL, `secure_delete`, rollback applicatif; writer unique à un instant | Très faible, zéro service | **Conserver** pour le socle Windows local |
| LangGraph + SQLite/Postgres checkpointer | Checkpoint par super-step, threads, reprise, time travel, pending writes | Chiffrement optionnel; schéma de state à versionner strictement | Nouvelle dépendance et second runtime d'orchestration | **S'inspirer du contrat**, ne pas remplacer Marvin |
| Mastra + LibSQL/Postgres | Snapshots de workflow et reprise; naturel pour un produit TypeScript | Données sérialisées, stockage partagé entre workflows | Dupliquerait FastAPI/Runner en Node; LibSQL reste proche de SQLite | **Ne pas intégrer** au backend Python |
| PostgreSQL + pgvector | Writers concurrents, multi-instance, réplication, RLS, SQL et vecteurs réunis | Bon choix serveur; secrets, service, sauvegardes et patching supplémentaires | Installation Windows et hors ligne plus lourde | **Option future** multi-utilisateur, pas défaut |
| Qdrant local actuel | Recherche vectorielle spécialisée, projection reconstruisible | Mono-process; local mode sans snapshots Qdrant natifs | Faible, déjà intégré | **Conserver**, surveiller taille et cohérence |
| Qdrant serveur | Snapshots, restauration et montée en charge vectorielle | Service réseau à authentifier, sauvegarder et limiter | Docker/service facultatif, port et cycle de vie en plus | **Option future** pour gros corpus |
| Microsoft Agent Framework | Checkpoints interchangeables et orchestration durable | File local ou Cosmos; types désérialisés à borner | Préversion et dépendance Azure possible | **Surveiller**, reprendre l'interface de store |

## LangGraph n'est pas une base de remplacement

LangGraph sépare :

- le **checkpointer**, état court d'un thread à chaque super-step ;
- le **Store**, mémoire partagée entre threads ;
- le moteur SQL réel, SQLite pour le local ou PostgreSQL pour la production distribuée.

Marvin possède déjà ces responsabilités sous d'autres formes : conversations, Coding Mission,
Mission OS, reçus d'actions, Evidence Store, mémoire SQLite et projection Qdrant. Brancher
LangGraph au-dessus créerait deux autorités de reprise. Le bon changement est une interface
`CheckpointStore` interne avec schéma versionné, parent, séquence, état, écritures en attente
et contrôle d'accès, puis des adaptateurs vers les stores actuels.

## Mastra, et non « MARVA »

Le document Kimi fourni par l'utilisateur cite **Mastra** parmi cinq frameworks. Mastra
persiste les snapshots de workflows dans LibSQL par défaut et propose d'autres stores. Il
confirme donc le choix d'une base SQLite-compatible pour un runtime local, mais son cœur
TypeScript dupliquerait le Runner FastAPI et la boucle agentique Python. Aucune migration
Mastra n'est retenue.

## Critères objectifs de promotion vers PostgreSQL

Une expérimentation PostgreSQL ne devient justifiée que si au moins un critère est mesuré :

- plusieurs processus ou PC doivent écrire simultanément dans la même base ;
- saturation durable du writer SQLite ou erreurs `database is locked` malgré les bornes ;
- besoin de haute disponibilité, réplication ou reprise sur un autre nœud ;
- séparation forte par plusieurs utilisateurs/tenants avec RLS ;
- volume ou requêtes analytiques dépassant les SLO définis ;
- obligation contractuelle d'un serveur de données administré.

Le passage ne doit pas mélanger base métier et mémoire vectorielle sans benchmark de rappel,
latence, coût disque et restauration.

## Plan d'amélioration sans migration

1. Définir un protocole `CheckpointStore` indépendant du moteur.
2. Adapter Coding Mission et Mission OS sans changer leur format durable.
3. Versionner le schéma de checkpoint et tester reprise depuis N-1.
4. Ajouter métriques de contention SQLite, taille WAL, latence et croissance par famille.
5. Définir un test de charge reproductible local et un seuil d'alerte.
6. Construire, uniquement si un seuil est franchi, un pilote PostgreSQL en double écriture
   de vérification sans basculer la lecture.
7. Comparer les résultats et exiger sauvegarde, restauration, migration descendante et
   rollback avant toute promotion.

## Sécurité, sauvegarde et rollback

Le benchmark utilise la base réelle en lecture seule et une base synthétique temporaire pour
les écritures. Il ne lit ni n'affiche aucune ligne métier. Aucun port, service, conteneur,
dépendance ou schéma n'est ajouté. Le rollback de cette tranche est la réversion atomique du
commit v2.470; les données ne nécessitent aucune restauration.

Une future preuve PostgreSQL ou Qdrant serveur devra être isolée, chiffrée en transit,
authentifiée, sans secret dans Git, avec moindre privilège, sauvegarde restaurée en test et
retour complet vers SQLite/Qdrant local avant acceptation.

## Sources primaires

- LangGraph, persistence et checkpointers :
  https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph, compatibilité des checkpoints :
  https://docs.langchain.com/oss/python/langgraph/backward-compatibility
- Mastra, snapshots de workflows :
  https://mastra.ai/en/reference/workflows/snapshots
- SQLite, Write-Ahead Logging :
  https://sqlite.org/wal.html
- pgvector :
  https://github.com/pgvector/pgvector
- Qdrant, stockage et WAL :
  https://qdrant.tech/documentation/manage-data/storage/
- Qdrant, snapshots :
  https://qdrant.tech/documentation/operations/snapshots/
- Microsoft Agent Framework, checkpoints :
  https://learn.microsoft.com/en-us/agent-framework/user-guide/workflows/checkpoints
