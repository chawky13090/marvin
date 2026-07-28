# Contrat de consolidation globale de Marvin

Date de référence : 2026-07-28
Version de départ : 2.386.0
Périmètre : tout le produit Marvin, du Runner à l'installateur Windows.

## 1. Objet et règle de preuve

Ce document est la source de vérité du chantier global. Il ne déclare pas Marvin « meilleur
que les IA de pointe » sans mesure reproductible. Il impose plutôt, pour chaque domaine :

1. une comparaison avec des références officielles et au moins deux solutions réalistes ;
2. un écart mesurable ou une preuve que le contrat courant est suffisant ;
3. des invariants fonctionnels interdisant la perte silencieuse de capacité ;
4. des tests de trajectoire et de résultat adaptés au risque ;
5. une preuve d'exécution réelle quand elle est sûre et non destructive ;
6. un rollback exact, vérifié avant chaque commit.
7. une amélioration proactive, utile et mesurable inspirée des meilleures pratiques ou
   innovations pertinentes; si aucune n'est justifiée, la décision de ne pas complexifier
   doit être motivée dans le journal.

Les statuts ont un sens strict :

- `verified` : le contrat, les tests et la preuve cités existent dans la version courante ;
- `partial` : des fondations existent, mais l'audit global ou une preuve manque ;
- `not_audited` : aucune conclusion n'est encore autorisée ;
- `blocked` : une dépendance externe empêche une preuve, sans masquer la limitation.

La présence de cette matrice ne constitue donc pas une certification. Seules les preuves
référencées dans une ligne permettent de promouvoir son statut.

## 2. Référentiel comparé

Les choix sont comparés à des sources primaires, puis adaptés au besoin réel d'un assistant
Windows installable plutôt que copiés mécaniquement :

- OpenAI Agents SDK : boucle d'agent, outils typés, sessions, guardrails, approbations,
  tracing et suivi d'usage — https://openai.github.io/openai-agents-python/
- Anthropic, *Building effective agents* : composants simples, workflows déterministes
  lorsque le chemin est connu, autonomie quand le problème est ouvert et vérité terrain —
  https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, *Demystifying evals for AI agents* : évaluer séparément trajectoire et résultat,
  combiner graders déterministes, modèles et humains, séparer capacité et non-régression —
  https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Anthropic, *Writing effective tools for agents* : contrats ciblés, descriptions explicites
  et amélioration pilotée par les évaluations —
  https://www.anthropic.com/engineering/writing-tools-for-agents
- Google Agent Development Kit : séparation Session/State/Memory, évaluation de trajectoire,
  callbacks et observabilité — https://adk.dev/sessions/ et https://adk.dev/evaluate/
- OWASP Agentic Security Initiative : menaces propres aux agents, aux outils et aux workflows
  multi-étapes — https://genai.owasp.org/initiatives/agentic-security-initiative/
- OpenTelemetry : conventions et corrélation portable des traces, métriques et journaux —
  https://opentelemetry.io/docs/specs/semconv/gen-ai/
- OpenTelemetry Logs Data Model : schéma structuré, sévérité et contexte de trace —
  https://opentelemetry.io/docs/specs/otel/logs/data-model/
- OWASP Logging Cheat Sheet : événements, données interdites, validation et rétention —
  https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
- NIST SP 800-92 Rev. 1 : cycle de vie complet de la gestion des journaux —
  https://csrc.nist.gov/pubs/sp/800/92/r1/ipd
- NIST AI RMF : gouverner, cartographier, mesurer et gérer les risques IA —
  https://www.nist.gov/itl/ai-risk-management-framework
- Microsoft : cycle de vie, sécurité, packaging et déploiement Windows —
  https://learn.microsoft.com/windows/apps/package-and-deploy/

## 3. Décision d'architecture globale

Deux stratégies réalistes sont retenues comme comparaison permanente :

| Approche | Avantages | Risques |
|---|---|---|
| Réécriture globale vers un nouveau framework agentique | homogénéité immédiate en théorie | rupture fonctionnelle, migration massive, dépendance fournisseur et rollback difficile |
| Consolidation progressive derrière les contrats existants | Marvin reste utilisable, preuves et rollback par tranche, corrections ciblées | coexistence temporaire de façades et cadence plus longue |

La consolidation progressive reste la stratégie par défaut. Une réécriture locale n'est
autorisée que si les tests démontrent que l'interface publique, les données, la confidentialité
et les parcours utilisateur sont préservés ou migrés de façon réversible.

Marvin reste un monolithe modulaire Windows-first. Les conteneurs et VM sont des environnements
de validation de livrables, pas une fragmentation obligatoire du produit.

## 4. Matrice exhaustive

| ID | Domaine | État | Preuve actuelle | Prochaine condition de promotion |
|---|---|---|---|---|
| runner | Runner et boucle agentique | verified | `scripts/test_agent_loop_policy.py`, `scripts/test_agent_execution.py`, `scripts/test_agent_turn_completion.py` | maintenir les contrats de budget, arrêt, reprise et événements |
| sessions | Sessions, SSE et reprise | verified | `scripts/test_chat_turn_runtime.py`, `scripts/test_chat_stream.mjs`, `scripts/test_agent_session.py` | test navigateur de reconnexion pendant un tour long |
| tools | Catalogue, harness et appels d'outils | partial | registre 344/344 contrôlé par `scripts/check_architecture.py` et tests par domaine | finir l'extraction, mesurer sélection, erreurs, approbations et résultat |
| models | Routage modèles, Council et confidentialité | partial | `scripts/test_agent_routing.py`, `scripts/test_agent_model_config.py`, `scripts/test_council.py` | matrice Cloud/local complète, provenance live et absence de repli interdit |
| memory | Mémoire, RAG et vérité durable | partial | `scripts/test_knowledge_mesh.py`, tests des domaines mémoire/documentaire | audit rétention, provenance, oubli, conflits et dérive factuelle |
| coding | Code Workspace, Forge et missions longues | partial | tests Code/Test Forge, production contract, Coding Mission et jobs | scénarios E2E Linux/Windows avec artefact et reprise après panne |
| isolation | Docker, VM Debian et VM Windows | partial | tests VM Lab, Hyper-V runner et Test Forge | preuves natives propres, snapshot/revert et réseau gouverné |
| persistence | SQLite, migrations et repositories | partial | inventaire 13 JSONL, preuves Forge, Mission OS, Coding Mission et Engineering Radar chaînées | consolider les flux métier restants, sauvegarde et restauration |
| api | FastAPI, contrats et compatibilité | partial | 346 routes uniques et `scripts/smoke_test_api.py` | schémas, erreurs, idempotence, autorisation et versionnement par famille |
| workers | Workers, cron et missions proactives | verified | tests supervisor, runtime workers, communication, cron et proactif | chaos tests arrêt/redémarrage, doublon et dépendance indisponible |
| observability | Logs, traces, métriques, coûts et évaluations | partial | audit JSONL, état Runner, Forge et gate reproductible | corrélation bout en bout, redaction, SLO et suites capacité/régression |
| security | Permissions, confirmations et guardrails | partial | 65 restrictions, gateway commun et tests de sécurité agent | threat model OWASP agentique complet et tests d'abus par surface |
| frontend | Frontend, accessibilité et expérience chat | partial | compilation/lint ciblés, 40 pages recensées et smoke Playwright | audit WCAG, états erreur/chargement/reprise et E2E des parcours critiques |
| avatar | Avatar de bureau et démarrage | partial | `scripts/test_avatar_api.py` et contrat installateur | test Electron réel démarrage/arrêt, déplacement, raccourcis et reprise |
| voice | Entrée/sortie vocale | partial | tests service proactif et sérialisation existante | test fonctionnel anti-chevauchement, interruption et changement de page |
| installer | Installation, mise à jour et désinstallation Windows | partial | `scripts/test_installer_contract.py`, preflight et health check | machine propre, reprise reboot, rollback mise à jour et désinstallation |

<!-- frontier-matrix
runner|verified
sessions|verified
tools|partial
models|partial
memory|partial
coding|partial
isolation|partial
persistence|partial
api|partial
workers|verified
observability|partial
security|partial
frontend|partial
avatar|partial
voice|partial
installer|partial
-->

## 5. Gate obligatoire par tranche

Une tranche n'est livrable que si les éléments applicables sont présents :

1. état initial et risque de perte fonctionnelle ;
2. comparaison d'au moins deux approches pour toute décision significative ;
3. choix motivé selon sécurité, résilience, maintenabilité, performance et dépendance ;
4. amélioration proactive évaluée face aux meilleures pratiques et innovations pertinentes ;
5. revue de sécurité obligatoire : surface d'attaque, validation des entrées, autorisation,
   secrets et données personnelles, concurrence, intégrité, dépendances, abus et test de
   non-régression. Toute dette restante doit être inventoriée, bornée, justifiée et planifiée;
   elle ne peut pas être masquée par un statut `verified` ;
6. impact de journalisation obligatoire : événements, corrélation, données interdites,
   rotation, rétention, panne du journal et test de non-divulgation selon
   `MARVIN-LOGGING-POLICY.md` ;
7. tests ciblés ajoutés avant ou avec la correction ;
8. compilation, architecture et gate rapide ;
9. validation HTTP ou UI réelle, sûre et non destructive ;
10. smoke test et contrôle des journaux ;
11. documentation dans `AGENTS.md` et `DEVELOPMENT-JOURNAL.md` ;
12. `git diff --check`, staging exact et contrôle du patch inverse ;
13. commit atomique, version alignée et commande de rollback documentée.

Les tests déterministes vérifient en priorité le résultat réel et les effets de bord. Les
évaluations LLM complètent ces tests pour la qualité ouverte, sans remplacer les assertions
objectives. Les secrets, e-mails et documents réels ne sont jamais envoyés à un grader sans
consentement explicite.

## 6. Rollback standard

Avant chaque commit, le patch indexé doit passer :

```powershell
git diff --cached --binary | git apply --cached --check --reverse
```

Après commit, le rollback standard est un `git revert <commit>` atomique. Une tranche qui
modifie un schéma, un format persistant, une VM ou une ressource externe doit en plus fournir
une migration descendante ou une restauration testée. Le retour arrière est ensuite validé
par le test ciblé, `scripts/check_architecture.py`, `/api/health` et le smoke test applicable.

## 7. Critère de clôture globale

Le chantier global ne peut être déclaré terminé que lorsque :

- aucune ligne n'est `not_audited`, `blocked` ou `partial` sans limitation acceptée et écrite ;
- les 344 outils gardent leur identité publique ou disposent d'une migration compatible ;
- les parcours chat, Code Workspace, e-mail, voix, avatar et installation passent réellement ;
- les suites de capacité et de non-régression sont distinctes et historisées ;
- les traces permettent de relier demande, décision, modèle, outil, effet, preuve et résultat ;
- une restauration de données et un rollback applicatif ont été exécutés avec succès ;
- les affirmations de qualité sont accompagnées de mesures, jamais d'un classement marketing.
