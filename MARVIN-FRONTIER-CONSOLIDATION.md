# Contrat de consolidation globale de Marvin

Date de référence : 2026-07-28
Version de départ : 2.386.0
Version courante auditée : 2.461.0
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

Le guide Kimi du 22 juillet 2026 constitue une veille secondaire utile pour sa synthèse
planificateur/exécutant/session/outils/checkpoints et son panorama LangGraph, CrewAI,
Microsoft Agent Framework, OpenAI Agents SDK et Mastra :
https://www.kimi.com/fr/resources/ai-agents-frameworks
Il est éditorial et promotionnel, pas une spécification. Aucune dépendance ni affirmation
technique (par exemple sandbox « native » ou niveau de fiabilité) n'est adoptée sans
confirmation dans la documentation primaire du framework et benchmark reproductible dans
Marvin.

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

### Écarts agentiques ajoutés après la veille Kimi

Marvin possède déjà les cinq primitives décrites dans le guide : planification,
exécution, état de session, outils/API et checkpoints Forge. Le plan n'ajoute donc pas un
framework généraliste par imitation. Il ajoute les contrats manquants suivants derrière les
frontières existantes :

1. **Graphe d'exécution typé et durable** : chaque nœud déclare entrée, sortie, précondition,
   budget, timeout, retry borné, compensation, preuve et état terminal. Le moteur existant
   Runner/Mission OS reste la base; LangGraph ou Microsoft Agent Framework ne sont retenus
   que s'ils battent ce socle sur reprise, maintenance, coût et sécurité.
2. **Handoffs versionnés** : Planner, chercheurs, Council, codeurs, vérificateurs et
   exécutants échangent des enveloppes typées avec objectif, contexte minimal, provenance,
   autorisations déléguées, budget et critère de fin. Aucun texte libre ne peut élargir une
   capacité ou une permission.
3. **Manifestes de capacités et permissions** : chaque outil expose version, schéma,
   effets de bord, réseau, données lues/écrites, confirmation, isolation, idempotence et
   rollback. Un futur adaptateur MCP consomme ces manifestes sans contourner le gateway des
   344 outils.
4. **Context engineering mesurable** : séparation formelle Session/State/Memory, budgets par
   source, snapshots de reprise, compression avec provenance et tests de perte d'information.
   Une grande fenêtre de contexte ne remplace pas cette discipline.
5. **Évaluation par nœud et bout en bout** : résultat, trajectoire, coût, latence, appels
   inutiles, violations de politique et qualité de reprise rejoignent Forge. Les graders LLM
   restent secondaires aux assertions déterministes et aux preuves d'exécution.
6. **Studio d'exécution lisible** : Mission Canvas affichera graphe, état, décisions,
   permissions, preuves, blocages, reprise et coût sans exposer les raisonnements privés ni
   noyer l'utilisateur dans les traces brutes.

Gate d'adoption d'un framework externe : threat model et provenance du paquet, versions
figées, SBOM/licence, maintenance, compatibilité Windows/Ollama Cloud, test de panne, migration
et rollback. Sans avantage mesuré face au moteur Marvin, la dépendance est refusée.

## 4. Matrice exhaustive

| ID | Domaine | État | Preuve actuelle | Prochaine condition de promotion |
|---|---|---|---|---|
| runner | Runner et boucle agentique | verified | `scripts/test_agent_loop_policy.py`, `scripts/test_agent_execution.py`, `scripts/test_agent_turn_completion.py` | maintenir les contrats de budget, arrêt, reprise et événements |
| sessions | Sessions, SSE et reprise | verified | `scripts/test_chat_turn_runtime.py`, `scripts/test_chat_stream.mjs`, `scripts/test_agent_session.py` | test navigateur de reconnexion pendant un tour long |
| tools | Catalogue, harness et appels d'outils | verified | registre 344/344, zéro consommateur direct, 78 restrictions, sélection/erreurs/approbations/résultats testés par `test_agent_tool_selection.py`, `test_tool_gateway.py`, `test_system_tools_gateway.py` et `test_engineering_runtime.py` | maintenir le gate et ajouter les nouveaux outils uniquement avec schéma, politique, résultat et preuves |
| models | Routage modèles, Council et confidentialité | verified | matrice des quatre profils, provenance SSE, Ultra Cloud-only, Council cinq familles, preuves génératives, découverte locale dynamique et classification privée par défaut des 344 outils; `test_model_data_policy.py` couvre dix familles négatives et les valeurs sensibles structurées | maintenir la liste positive publique, les tests Cloud-only/Council et le défaut privé pour tout nouvel outil |
| memory | Mémoire, RAG et vérité durable | partial | autorité SQLite, contenu SQLite/Qdrant chiffré, audit/réparation 10/10/10, quarantaine de fraîcheur, rétention déterministe et restauration compensée (`test_memory_encryption.py`, `test_memory_lifecycle.py`, `test_memory_recovery.py`) | valider la restauration isolée de bout en bout et l'exclusion live des faits périmés avant promotion |
| coding | Code Workspace, Forge et missions longues | verified | mission réelle `da59b089bff44e77974d7d35324e88b3`, Delivery Pack accepté, réparation après échecs, artefact préservé, 12 tests Windows et 12 tests Debian + Bats | maintenir les gates E2E, le rejeu ciblé et l'absence de régression d'artefact |
| isolation | Docker, VM Debian et VM Windows | verified | Docker hors ligne sans socket hôte; Windows 11 non-admin réseau coupé; Debian 13 native; checkpoints restaurés avant/après; smokes live et mission v2.457 | maintenir les images figées, le moindre privilège, la gouvernance réseau et les restaurations |
| persistence | SQLite, migrations et repositories | partial | 14 JSONL classifiés, repositories injectables, preuves chaînées et bundle global AES-256-GCM/DPAPI vérifié sur 1 066 fichiers; restauration isolée SHA-256 complète | ajouter application hors ligne compensée et export portable/hors machine avant promotion |
| api | FastAPI, contrats et compatibilité | partial | 354 routes uniques et `scripts/smoke_test_api.py` | schémas, erreurs, idempotence, autorisation et versionnement par famille |
| workers | Workers, cron et missions proactives | verified | tests supervisor, runtime workers, communication, cron et proactif | chaos tests arrêt/redémarrage, doublon et dépendance indisponible |
| observability | Logs, traces, métriques, coûts et évaluations | partial | audit JSONL, état Runner, SLO HTTP roulant, Forge, corrélation HTTP→Runner→outils→SQLite/audit et gate reproductible | alertes et suites capacité/régression |
| security | Permissions, confirmations et guardrails | partial | 65 restrictions, gateway commun et tests de sécurité agent | threat model OWASP agentique complet et tests d'abus par surface |
| frontend | Frontend, accessibilité et expérience chat | partial | compilation/lint ciblés, 40 pages recensées et smoke Playwright | audit WCAG, états erreur/chargement/reprise et E2E des parcours critiques |
| avatar | Avatar de bureau et démarrage | partial | `scripts/test_avatar_api.py` et contrat installateur | test Electron réel démarrage/arrêt, déplacement, raccourcis et reprise |
| voice | Entrée/sortie vocale | verified | test frontend statique et smoke navigateur de sérialisation, navigation et interruption | maintenir le parcours dans le gate de non-régression |
| installer | Installation, mise à jour et désinstallation Windows | partial | `scripts/test_installer_contract.py`, preflight et health check | machine propre, reprise reboot, rollback mise à jour et désinstallation |

<!-- frontier-matrix
runner|verified
sessions|verified
tools|verified
models|verified
memory|partial
coding|verified
isolation|verified
persistence|partial
api|partial
workers|verified
observability|partial
security|partial
frontend|partial
avatar|partial
voice|verified
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
   aucune dette de sécurité ne peut être ignorée et elle ne peut pas être masquée par un
   statut `verified` ;
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

## 8. Exigences non négociables consolidées

Cette section rassemble les demandes successives afin qu'une amélioration locale ne fasse
jamais oublier l'objectif produit. Elles s'appliquent à toutes les phases pertinentes.

### 8.1 Architecture et qualité du code

- consolider tout le projet, pas uniquement `main.py`, le backend ou la sécurité ;
- conserver un monolithe modulaire installable, avec frontières Runner, sessions, outils,
  guardrails, persistance, observabilité et composition explicites ;
- garder un cœur logiciel déterministe pour les permissions, validations, budgets, effets de
  bord, confirmations, idempotence, reprise, preuves et état terminal ;
- laisser aux LLM la liberté de planifier, rechercher, critiquer et choisir dans l'enveloppe
  autorisée; le déterminisme ne doit pas remplacer le raisonnement ouvert ;
- comparer toute décision significative à au moins deux approches et aux sources primaires
  pertinentes d'OpenAI, Anthropic, Google, Microsoft, Ollama, OWASP, NIST ou de l'écosystème
  concerné ;
- améliorer le composant pendant son extraction lorsque la preuve montre un défaut réel,
  sans réécriture opportuniste ni réduction de fonctionnalité ;
- préserver les façades, routes, outils, données et parcours existants ou fournir une
  migration compatible et réversible ;
- rendre les chemins, dossiers de travail, ISO, VM, documents et artefacts dynamiques et
  portables entre comptes et machines Windows ;
- maintenir une arborescence Marvin dédiée et gouvernée pour projets, documents, preuves,
  caches, modèles, ISO, VM et exports, sans chemins liés à la machine de développement.

### 8.2 Intelligence, modèles et autonomie

- Ollama Cloud est la puissance normale; les modèles locaux sont réservés aux profils de
  confidentialité et à la continuité hors ligne ;
- le profil Ultra débridé reste strictement Cloud-only : aucun repli local silencieux ;
- Council utilise cinq familles de modèles Cloud distinctes avec panel, critique aveugle,
  arbitrage, provenance et gestion explicite des indisponibilités ;
- Model Market rend tous les modèles Ollama Cloud compatibles découvrables et sélectionne le
  meilleur modèle selon la tâche, les mesures, les capacités et la politique de données ;
- Research Swarm, Cortex Search et les vérificateurs spécialisés doivent améliorer la qualité
  par recherche, contradiction et synthèse, sans multiplier des appels inutiles ;
- le mode Auto poursuit une mission jusqu'au succès vérifié ou jusqu'à un état explicite
  `needs_user`, `policy_blocked`, `dependency_blocked`, `cancelled` ou `failed_terminal`;
  aucune limite arbitraire de 120 minutes ne constitue à elle seule une réussite ou un échec ;
- une mission interrompue reprend depuis le dernier checkpoint cohérent, sans perdre le travail
  déjà validé, avec retries bornés par étape, backoff, budget et diagnostic ;
- le chat d'origine reste la vue autoritaire de progression : étapes, outils, blocages,
  reprises, preuves et résultat y sont publiés même si Code Workspace ou Mission Canvas
  fournit une vue spécialisée.

### 8.3 Code Workspace, Forge et validation de production

- une demande de code peut être saisie directement dans le chat général ou dans Code
  Workspace; les deux chemins créent le même contrat de Coding Mission ;
- Marvin inspecte le dépôt, planifie, modifie, exécute, observe l'erreur, corrige et recommence
  jusqu'à satisfaire les critères objectifs du livrable ;
- le code Windows et Linux doit être vérifié sur la cible réelle compatible : conteneur
  jetable quand il suffit, VM Debian pour le noyau Linux ou les services système, VM Windows
  pour les applications et scripts Windows natifs ;
- les environnements de test peuvent accéder au Web pour installer et tester des dépendances,
  mais avec politique réseau déclarée, délais, quotas, provenance et journalisation ;
- les VM de validation reviennent à un checkpoint propre après le test; une conservation
  temporaire pour inspection utilisateur est proposée avant le revert ;
- cross-compilation, analyse statique et exécution native ne sont jamais confondues dans les
  preuves ;
- Knowledge Radar suit les versions, documentations officielles, conventions, avis de
  sécurité et toolchains nécessaires, avec date et provenance ;
- aucun livrable n'est qualifié « production » sans installation reproductible, lint,
  compilation/type-check, tests adaptés, analyse de dépendances, SBOM, artefact, preuve
  d'exécution et limites connues.

### 8.4 Données, preuves, logs et sécurité

- les preuves métier utiles sont conservées plus longtemps que les logs de diagnostic :
  résultat, approbation, artefact, hash, provenance et décision de conservation sont des
  enregistrements gouvernés, pas des lignes de log jetables ;
- logs, traces, métriques et preuves possèdent une classification, un propriétaire, une durée
  de rétention, une limite disque, une rotation, une purge vérifiable et une procédure
  d'export/restauration ;
- toute demande, décision de modèle, appel d'outil, effet, preuve et résultat est corrélable
  sans journaliser secret, mot de passe, token, contenu sensible inutile ou raisonnement privé ;
- chaque composant subit une revue de sécurité obligatoire; la sécurité est un gate
  transversal et non une phase isolée qui remplace la consolidation fonctionnelle ;
- aucune dette de sécurité découverte n'est ignorée : elle est corrigée dans la tranche ou
  enregistrée avec sévérité, exposition, mitigation, propriétaire logique, condition de
  fermeture et test ;
- secrets, sauvegardes et données sensibles au repos sont protégés selon un mécanisme standard,
  avec migration idempotente, restauration testée et parcours de réauthentification portable ;
- les outils sont tous soumis au même harness : schéma fermé, capacité, permission, effet de
  bord, confirmation, idempotence, isolation, timeout, sortie bornée, preuve, audit et
  compensation applicables ;
- aucun adaptateur MCP, UI, worker, cron ou appel interne ne contourne ce gateway.

### 8.5 Expérience utilisateur, avatar, voix et distribution

- le frontend doit rendre les conversations longues lisibles, conserver les messages et
  événements partiels lors d'un changement de page et restaurer exactement un stream en cours ;
- les états chargement, réflexion, outil, erreur, blocage, reprise et succès doivent être
  compréhensibles sans consulter des journaux ou Code Workspace ;
- Code Forge, Test Forge, Knowledge Radar, Council et les modes utiles sont accessibles et
  expliqués depuis les surfaces de chat, sans boutons inertes ni vocabulaire ambigu ;
- l'avatar de bureau offre démarrage/arrêt de Marvin, raccourci bureau et UI, déplacement
  fiable, fenêtre de chat exploitable, entrée vocale directe et état du runtime ;
- l'identité visuelle cible associe une boucle de Möbius 3D animée à un robot intelligent et
  malicieux, tout en respectant performances, accessibilité et préférence de mouvement réduit ;
- la voix est sérialisée : une seule restitution active par session, interruption explicite,
  annulation lors d'un changement de contexte et aucune superposition de messages ;
- l'installateur final est Windows-first, en un clic, idempotent et portable : détection des
  capacités, élévation minimale, reprise après redémarrage, diagnostic, mise à jour,
  réparation, rollback et désinstallation propre ;
- Hyper-V, Docker, Windows Sandbox, GPU, Ollama local et Ollama Cloud restent des capacités
  optionnelles; leur absence ne bloque pas le socle et produit un état
  `disponible`, `dégradé` ou `indisponible` avec repli honnête.

## 9. Feuille de route d'exécution révisée

L'ordre ci-dessous est contraignant par dépendance, mais une correction bloquante peut être
traitée plus tôt. Chaque phase hérite intégralement du gate de la section 5.

| Ordre | Phase | État au 2.415.0 | Livraison et condition de sortie |
|---:|---|---|---|
| 0 | Gouvernance continue | partial | matrice, dette sécurité, politique de logs, inventaire des persistances, journal et rollback restent synchronisés à chaque tranche |
| 1 | Composition backend | verified | `main.py` contient uniquement composition, lifespan et handler global; 47 routeurs, cycle de vie, imports acycliques et import borné sont testés |
| 2 | Persistance modulaire | partial | `database.py` devient une façade; repositories par agrégat, transactions, concurrence, migrations montantes/descendantes, sauvegarde et restauration réelles |
| 3 | Graphe agentique déterministe | partial | graphe durable typé, handoffs versionnés, états terminaux, checkpoints, compensations et manifestes de capacités pour Runner/Mission OS |
| 4 | Harness universel des outils | partial | 344/344 outils et tous leurs consommateurs passent exclusivement par validation, permissions, idempotence, preuve et observabilité communes |
| 5 | Profils de confidentialité et autorisations | partial | Normal, Hyper sécurisé, Tout cloud et Ultra débridé ont des contrats distincts; niveaux Sécurisé/Standard/Expert orthogonaux; transitions, provenance, replis et refus sont testés |
| 6 | Intelligence Cloud et évaluation | partial | Ultra Cloud-only prouvé, Council cinq familles live, Model Market/Research Swarm mesurés, Cortex et vérificateurs évalués sur qualité, coût et appels inutiles |
| 7 | Code Workspace et Forge autonome | partial | demande chat/workspace unifiée, boucle corriger-tester, reprise visible, validations natives Debian/Windows, checkpoint propre et livrable de production démontré |
| 8 | Memory Mesh, Truth Ledger et rétention | partial | séparation Session/State/Memory, provenance, conflits, oubli, chiffrement, preuves métier durables et politiques de rétention/restauration validées |
| 9 | Observabilité et SRE | partial | corrélation bout en bout, logs structurés expurgés, métriques/SLO, rotation/purge, alertes, chaos tests et tableaux de santé exploitables |
| 10 | Fermeture de la dette sécurité | partial | threat model agentique complet, API/auth réseau, secrets e-mail/SSH/OAuth, sauvegardes chiffrées, ACL et tests d'abus fermés ou limitations explicitement acceptées |
| 11 | Frontend et Mission Canvas | partial | UX accessible, conversations/streams robustes, progression lisible, modes et Forges actionnables, tests Playwright des parcours critiques |
| 12 | Avatar et voix | partial | Electron réel validé pour démarrage/arrêt/déplacement/raccourcis; avatar Möbius; voix sans chevauchement; reprise et accessibilité |
| 13 | Installateur Windows | partial | installation machine propre, chemins dynamiques, capacités optionnelles, reboot/reprise, réparation, update, rollback et désinstallation réellement exécutés |
| 14 | Evolution Lab et audit final | not_audited | benchmark capacité/non-régression, optimisation contrôlée, restauration catastrophe, rollback global, documentation opérateur et matrice sans preuve manquante |

### Brique obligatoire — profils et autorisations

Les profils de confidentialité et les niveaux d'autorisation ne doivent plus être confondus.
La consolidation doit produire une matrice exécutable et testée :

- **Normal** : Cloud Ollama prioritaire pour la qualité, repli local seulement si la politique
  de sensibilité l'autorise et avec provenance visible ;
- **Hyper sécurisé** : traitement local obligatoire, aucune sortie Cloud ni télémétrie de
  contenu, échec explicite si la capacité locale manque ;
- **Tout cloud** : modèles Cloud autorisés et prioritaires, mais garde-fous d'actions et
  confirmations inchangés ;
- **Ultra débridé** : Cloud-only strict, liberté maximale du LLM dans le périmètre demandé,
  jamais de repli local silencieux et provenance de chaque modèle vérifiable ;
- **Sécurisé / Standard / Expert** : axe orthogonal contrôlant uniquement permissions,
  confirmations et portée des effets; changer ce niveau ne change pas implicitement la
  destination des données.

Chaque combinaison doit être couverte par tests positifs et négatifs sur chat, Council,
outils, mémoire, documents, e-mails et Code Workspace. Une transition en cours de mission
doit créer un événement durable, recalculer les capacités et ne jamais réinterpréter
rétroactivement une autorisation déjà refusée.

### Phase active

La phase **1 — Composition backend** est vérifiée en v2.403.0 :

- les cinq routes historiques restantes sont dans deux `APIRouter` typés ;
- `main.py` est passé de 3 391 à 276 lignes sans perdre aucun des 45 routeurs antérieurs ni
  aucun des 15 workers; les deux routeurs supplémentaires sont les extractions attendues ;
- un contrat contrôle les 47 routeurs, les imports inutilisés, l'absence de cycle top-level,
  l'import borné à 30 secondes et la fermeture ordonnée du lifespan ;
- la gate globale a réussi sur 171 étapes.

La phase active devient **2 — Persistance modulaire**. L'inventaire AST et transactionnel de
`database.py` a confirmé dix agrégats et de nombreux consommateurs de façade. La première
frontière, les paramètres globaux, rejoint `repositories/settings.py` en v2.405.0 avec
injection de connexion, compatibilité JSON et SQL paramétré. En v2.406.0, mémoires, tâches et
notes rejoignent trois repositories séparés, injectables et testés sans modifier les quinze
fonctions de façade. L'agenda local et les miroirs externes rejoignent à leur tour un
repository injectable en v2.407.0, avec remplacement par source atomique et migration
défensive. En v2.408.0, projets, captures et logos rejoignent trois repositories séparés;
leurs neuf façades et relations sont testées sur SQLite réel. En v2.409.0, les traces
d'outils et la fiabilité ont rejoint un stockage technique borné et expurgé, distinct des
preuves métier durables. En v2.410.0, inventaire réseau, snapshots système, modèles d'outils
et tâches cron rejoignent quatre repositories injectables avec transactions, index, bornes
et compatibilité des quatorze façades. En v2.411.0, la facturation rejoint un agrégat
injectable unique : vingt façades compatibles, numérotation transactionnelle concurrente,
montants finis, paiements bornés, cascade et rollback testés. La progression reste pilotée
par agrégat cohésif et risque réel, jamais par le seul nombre de lignes. En v2.412.0, les
contrôles opérationnels rejoignent un repository injectable qui garantit la cohérence entre
checklist, point, résultat et preuve sans tronquer les preuves métier. En v2.413.0, la
documentation technique rejoint un repository injectable séparé de son catalogue statique :
quatorze façades restent compatibles et la numérotation annuelle résiste aux collisions,
rollbacks et créations concurrentes. En v2.414.0, la santé client rejoint un repository
injectable : création du score, de ses points et recommandations dans une transaction unique,
valeurs numériques bornées, lecture stable et rollback vérifié. En v2.415.0, les analyses de
commandes et approbations rejoignent un repository injectable : catalogue historique exact,
liaison analyse/commande et transition finale idempotente sont désormais déterministes.
En v2.417.0 et v2.418.0, fiches de révision puis connaissances IT terminent l'extraction
des agrégats de `database.py`; la façade ne conserve plus que la composition des schémas.
En v2.419.0, sauvegarde et restauration utilisent l'Online Backup API sous un service
sérialisé, avec publication atomique, contrôles SQLite, SHA-256, rotation couplée et
compensation automatique testée. La phase reste `partial` tant que SEC-005 n'a pas livré
le format chiffré authentifié, la migration des sauvegardes historiques et sa restauration
réelle sous le compte Windows.

En v2.420.0, cette limite est levée : chaque nouvelle sauvegarde est un conteneur versionné
AES-256-GCM dont la clé de données aléatoire est enveloppée par DPAPI utilisateur. Le service
conserve la lecture des `.db` historiques, tandis qu'une migration explicite fournit dry-run,
montée et descente idempotente sans écrasement de collision. La preuve réelle a exécuté une
montée de 14 fichiers, une descente de 15 fichiers, puis une remontée de 15 fichiers et une
restauration logique exacte. La non-portabilité DPAPI reste explicitement suivie par SEC-012.
En v2.421.0, l'intégrité relationnelle des tours SSE est réparée sans perte de preuve :
les orphelins rejoignent une archive métier durable avant suppression, les connexions
échouent si `foreign_keys` n'est pas actif et chaque insertion vérifie indépendamment son
parent. La base réelle passe de 27 à zéro violation FK; les 27 lignes archivées correspondent
exactement au snapshot chiffré préalable.
En v2.422.0, les secrets des comptes e-mail quittent le JSON SQLite pour des enveloppes
DPAPI isolées par compte. La résolution reste derrière la façade existante, les mises à jour
et suppressions compensent les pannes croisées, et la migration comme le rollback refusent
les états non relus. Trois comptes réels ont migré avec zéro secret logique résiduel et
trois connexions IMAP/SMTP validées sans effet métier sortant.
En v2.423.0, les secrets SSH persistants utilisent une enveloppe DPAPI par connexion et les
colonnes historiques sont nettoyées après relecture. Les connexions ponctuelles ne sont pas
persistées. Les mutations compensent les pannes entre coffre et SQLite, tandis que toutes
les surfaces HTTP/SSE/WebSocket/SFTP remplacent les exceptions brutes par une catégorie
expurgée et un audit sans contenu.
En v2.424.0, FastAPI devient l'unique propriétaire OAuth Google/Microsoft. Les anciennes
routes Next.js redirigent vers lui et leurs callbacks incompatibles sont fermés explicitement.
Les jetons historiques sont protégés et relus dans DPAPI avant nettoyage; la migration 6
remplace les colonnes secrètes par un tombstone de métadonnées. La base réelle est saine et
le rollback exact est testé. La phase Persistance reste `partial` jusqu'à la fermeture ou
l'acceptation explicite des dettes restantes, notamment compte de service Google, ACL,
cycle de vie des secrets et portabilité.
En v2.425.0, le bootstrap SQLite quitte la façade `database.py`. Les treize repositories,
la migration de secrets externe, la frontière de commit et les migrations SQL forment un
composition root déterministe, injectable et testé en panne. `database.py` ne contient plus
de fonction active : il reste une façade de compatibilité, sans changement d'identité publique.
En v2.426.0, la dernière écriture SQLite côté Next.js disparaît : FastAPI devient le seul
propriétaire du fichier, du schéma et du réglage `active_model`. `better-sqlite3` et ses
contraintes ABI quittent la dépendance, le preflight, l'installateur et Turbopack. Les
frontières HTTP sont bornées et les erreurs Next corrélées sans contenu interne.
En v2.427.0, le runtime durable des tours ferme ses états terminaux par énumération et
expurge les erreurs du producteur avant toute sortie SSE ou persistance SQLite. Un incident
opaque relie l'interface au journal technique, qui ne conserve que la classe d'erreur et un
condensat du request ID. La panne du logger ne peut plus laisser le tour en cours indéfiniment.
En v2.428.0, la même règle s'applique aux événements déjà formés par le transport Ollama :
corps HTTP distant, exception, traceback, endpoint et modèle ne sont jamais projetés dans le
chat. Catégorie opérationnelle, code HTTP sûr et incident opaque préservent le diagnostic.
En v2.429.0, la frontière outils étend ce contrat aux exécuteurs, reçus idempotents et pont
MCP. Les pannes d'observation ne sont plus silencieuses : elles accompagnent le résultat sous
une projection bornée et sans donnée métier. Les 344 schémas et exécuteurs restent identiques.
En v2.430.0, le routage modèle devient vérifiable depuis le chat : fournisseur, mode de
confidentialité, Cloud-only et classification accompagnent chaque sélection et escalade.
Une compétence promue vers Agent utilise également le modèle Agent comme repli local sûr,
préservant la qualité en mode hybride sans affaiblir Hyper local ou Ultra Cloud-only.
En v2.431.0, SQLite devient la source autoritative d'un cycle de vie commun avec Memory Mesh
et Qdrant. Création, enrichissement, oubli, purge et consolidation utilisent la même
frontière; une panne de projection reste visible et aucun oubli incomplet n'est déclaré
réussi. Les souvenirs échus quittent immédiatement le prompt puis sont purgés par le worker.
Un Mesh corrompu échoue fermé et n'est plus remplacé silencieusement.
En v2.432.0, Code Workspace sépare formellement candidat, validation et intégration : les
fichiers n'atteignent le worktree qu'après tous les gates, tandis qu'un refus alimente le
snapshot de réparation sans laisser de fichier périmé. Le registre des jobs possède une
copie valide, des écritures synchronisées, une récupération explicite et un état dégradé
visible. Cette amélioration suit les principes communs aux agents de code modernes :
environnement isolé, checkpoints, preuve de tests et restauration avant intégration.
En v2.433.0, l'arbitrage de ressources aligne le runtime sur le contrat Cloud-first : aucun
modèle local n'est préchargé quand Cloud est actif hors Hyper local. Debian et Windows
publient un précheck RAM avant démarrage. Les deux runners ont exécuté réellement un bundle
et ses tests dans leurs VM propres avec restauration du checkpoint avant et après; cette
preuve ferme le défaut d'exécution native simple, mais pas encore l'E2E complet d'une mission
LLM autonome interrompue puis reprise.
En v2.434.0, la boucle `diagnostic → réparation ciblée → revalidation` devient un contrat
observable commun au chat et à Code Workspace. Les événements sont conservés dans le registre
chaîné de la Coding Mission, les phases longues publient un check-up toutes les trente
secondes, et chaque Delivery Pack garde les sources officielles réellement injectées au
raisonnement avec URL, fraîcheur et empreinte. Un heartbeat ne vaut jamais preuve de progrès :
seuls les checkpoints, rapports d'exécution et gates déterministes permettent l'acceptation.

## 10. Preuves minimales par grande capacité

| Capacité | Preuve exigée avant `verified` |
|---|---|
| Chat et sessions | reconnexion navigateur pendant génération et outil, événements sans trou ni doublon, reprise après redémarrage |
| Outils | identité 344/344, schéma/permission/effect testés, erreurs bornées, compensation et audit |
| Council/Cloud | cinq familles distinctes réellement appelées, provenance, aucune exécution locale en Ultra |
| Code | dépôt réel, modification réelle, échec observé puis correction, tests natifs et artefact relu |
| VM/conteneur | état propre initial, réseau annoncé, résultat invité, export de preuve, arrêt et revert vérifiés |
| E-mail | plusieurs comptes, plusieurs expéditeurs autorisés, simulation, anti-boucle, confirmation et panne partielle |
| Mémoire | provenance, contradiction, oubli sélectif, rétention et restauration |
| Frontend | Playwright desktop et viewport réduit, changement de page pendant stream, erreurs et clavier |
| Avatar/voix | application Electron réelle, raccourci, déplacement, ouverture Marvin, interruption et non-chevauchement |
| Installateur | VM Windows propre, install/reboot/repair/update/uninstall, aucune dépendance machine cachée |
| Données | sauvegarde cohérente, restauration isolée, intégrité, migration/rollback et absence de secret logique |
| Observabilité | identifiant de corrélation traversant Runner, modèle, outil, effet, preuve et réponse sans donnée interdite |

## 11. Règle d'évolution du plan

Une découverte peut modifier l'ordre ou la solution, jamais supprimer silencieusement une
exigence. Toute révision doit :

1. citer le fait nouveau et la preuve ;
2. comparer au moins deux options ;
3. montrer l'impact sur toutes les phases dépendantes ;
4. conserver ou migrer les critères de réussite ;
5. mettre à jour ce document, le plan spécialisé concerné et `DEVELOPMENT-JOURNAL.md` ;
6. rester réversible par commit ou migration documentée.
