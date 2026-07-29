# Inventaire des journaux et flux événementiels Marvin

Date de référence : 2026-07-28
Version du contrat : 1.0

## 1. Décision

Un fichier JSONL n'est pas automatiquement un journal technique. Marvin distingue :

- `technical_log` : télémétrie de diagnostic ou de sécurité, expurgée et supprimée à
  l'échéance définie dans `MARVIN-LOGGING-POLICY.md` ;
- `domain_event_stream` : historique nécessaire à la reprise d'une mission ou à la
  reconstruction d'un état; sa suppression suit le cycle de vie de l'objet propriétaire ;
- `evaluation_ledger` : preuves Forge, Arena et observations de modèles nécessaires aux
  comparaisons historiques; archivage ou suppression explicite, jamais rotation aveugle ;
- `truth_ledger` : faits et contradictions gouvernés par le contrat de mémoire.

Les preuves métier sont conservées par défaut avec leur mission, projet ou registre
propriétaire. Elles ne sont jamais supprimées par la rotation d'un log technique. Une
suppression doit être explicite et confirmée; un archivage doit conserver schéma, ordre,
horodatage, empreintes et liens vers les artefacts. Une correction ajoute un événement
compensatoire ou une nouvelle version au lieu de réécrire silencieusement la preuve initiale.

Deux approches ont été comparées :

| Approche | Avantage | Risque |
|---|---|---|
| Appliquer rotation et rétention à tous les JSONL | uniformité apparente | perte de missions, preuves, votes ou vérité durable |
| Classifier par finalité et propriétaire | cycle de vie correct, reprise préservée | inventaire et migrations spécifiques nécessaires |

La seconde approche est retenue. Le modèle Event Sourcing recommande de traiter un flux
métier append-only comme une source de données durable, avec versionnement, ordre,
idempotence et événements compensatoires, et non comme un simple fichier de logs :
https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing

## 2. Inventaire autoritaire

| Module et fichier | Classe | Propriétaire | Cycle de vie | État |
|---|---|---|---|---|
| `audit.py` — `audit.jsonl` | technical_log | sécurité/opérations | 90 jours | structuré |
| `bug_log.py` — `bug_log.jsonl` | technical_log | incidents | 30 jours | structuré |
| `skills.py` — `skills_match_log.jsonl` | technical_log | matcher de compétences | 30 jours | structuré |
| `api_observability.py` — `api_requests.jsonl` | technical_log | erreurs et latences HTTP | 30 jours | structuré |
| `coding_mission.py` — `events.jsonl` | domain_event_stream | Coding Mission | avec la mission | structuré |
| `engineering_radar.py` — `events.jsonl` | domain_event_stream | Radar documentaire | avec l'état Radar | structuré |
| `mission_os.py` — `mission_events.jsonl` | domain_event_stream | Mission OS | avec la mission | structuré |
| `forge.py` — `forge_runs.jsonl` | evaluation_ledger | Marvin Forge | avec le corpus Forge | structuré |
| `frontier_arena.py` — `frontier_arena_submissions.jsonl` | evaluation_ledger | Frontier Arena | archivage explicite | structuré |
| `frontier_arena.py` — `frontier_arena_matches.jsonl` | evaluation_ledger | Frontier Arena | archivage explicite | structuré |
| `frontier_arena.py` — `frontier_arena_votes.jsonl` | evaluation_ledger | Frontier Arena | archivage explicite | structuré |
| `model_market.py` — `model_market_observations.jsonl` | evaluation_ledger | Model Market | archivage explicite | structuré |
| `research_swarm.py` / `research_engine_v3.py` — `research_swarm_runs.jsonl` | evaluation_ledger | Recherche approfondie v2/v3 | archivage explicite | structuré |
| `truth_ledger.py` — `truth_ledger.jsonl` | truth_ledger | Memory Mesh | contrat mémoire | structuré |

<!-- persistence-inventory
backend/audit.py|audit.jsonl|technical_log|90d|structured
backend/bug_log.py|bug_log.jsonl|technical_log|30d|structured
backend/skills.py|skills_match_log.jsonl|technical_log|30d|structured
backend/api_observability.py|api_requests.jsonl|technical_log|30d|structured
backend/coding_mission.py|events.jsonl|domain_event_stream|owner_lifecycle|structured
backend/engineering_radar.py|events.jsonl|domain_event_stream|owner_lifecycle|structured
backend/mission_os.py|mission_events.jsonl|domain_event_stream|owner_lifecycle|structured
backend/forge.py|forge_runs.jsonl|evaluation_ledger|owner_lifecycle|structured
backend/frontier_arena.py|frontier_arena_submissions.jsonl|evaluation_ledger|explicit_archive|structured
backend/frontier_arena.py|frontier_arena_matches.jsonl|evaluation_ledger|explicit_archive|structured
backend/frontier_arena.py|frontier_arena_votes.jsonl|evaluation_ledger|explicit_archive|structured
backend/model_market.py|model_market_observations.jsonl|evaluation_ledger|explicit_archive|structured
backend/research_swarm.py|research_swarm_runs.jsonl|evaluation_ledger|explicit_archive|structured
backend/truth_ledger.py|truth_ledger.jsonl|truth_ledger|memory_contract|structured
-->

## 3. Invariants de migration

Pour chaque flux restant :

1. préserver les identités, l'ordre et les lecteurs publics ;
2. ajouter `schema_version`, identifiant stable et timestamp UTC si absents ;
3. borner entrées, tailles et lectures sans supprimer une preuve requise ;
4. définir concurrence, reprise après ligne partielle et tolérance de schéma ;
5. expurger secrets et contenus selon la finalité, sans détruire les données métier requises ;
6. ajouter tests d'idempotence, concurrence, corruption partielle et rollback ;
7. ne promouvoir `pending` vers `structured` qu'après preuve ciblée et gate global.
8. conserver les preuves métier jusqu'à suppression confirmée de leur propriétaire ou
   archivage vérifié; aucune durée arbitraire n'est appliquée par défaut.

Le test `scripts/test_persistence_inventory.py` échoue dès qu'un nouveau chemin JSONL backend
n'est pas classifié. Les environnements virtuels et dépendances tierces sont exclus.

## 4. Rollback

Le manifeste est réversible par `git revert <commit>`. Une migration de journal technique
peut supprimer intentionnellement un contenu sensible historique; ce contenu brut n'est pas
sauvegardé et n'est donc pas restaurable. Les empreintes, scores et métadonnées non sensibles
restent disponibles. Les flux métier ne sont jamais réécrits dans cette tranche.
