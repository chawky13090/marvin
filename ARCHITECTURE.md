# Architecture de Marvin

Ce document décrit les frontières stables du projet. Il complète l’historique détaillé de
`backend/main.py` sans le dupliquer.

## Flux principal

```mermaid
flowchart LR
    UI["Next.js / React"] -->|"SSE / REST"| API["FastAPI"]
    API --> AGENT["Boucle agentique"]
    AGENT --> ROUTER["Routage outils et compétences"]
    ROUTER --> TOOLS["363 outils"]
    AGENT --> OLLAMA["Ollama local / confidentialité"]
    AGENT --> CLOUD["Ollama Cloud / puissance"]
    API --> SQLITE["SQLite"]
    API --> QDRANT["Qdrant local"]
```

## Responsabilités backend

| Module | Responsabilité |
|---|---|
| `main.py` | Composition FastAPI, lifespan, montage des routeurs et handler global ; aucune route métier |
| `runtime_supervisor.py` | Propriété, déduplication, observation et arrêt idempotent des workers FastAPI |
| `runtime_workers.py` | Préchauffage et workers transverses de maintenance, sans dépendance à FastAPI |
| `communication_workers.py` | Boucles e-mail et agenda, réglages persistants et appels d'outils historiques |
| `proactive_service.py` | Briefings, anticipation, heures calmes et lecture vocale proactive |
| `cron_runtime.py` | Jobs planifiés, journal d'exécution et reprise bornée des tâches longues |
| `api/` | Routeurs par domaine : données, métiers, voix, agenda, IA, connexions, SSH, planification, monitoring et santé |
| `scheduling.py` | Parsing unique des planifications utilisé par l'API Cron et son worker |
| `agent.py` | Composition du Runner : session, contexte, itérations et délégation aux frontières spécialisées |
| `agent_policy.py` | Politiques textuelles pures : titres et noms d'outils explicitement cités |
| `agent_prompt.py` | Prompt système, permissions, chemins dynamiques, mémoire et date déterministe |
| `agent_safety.py` | Validation pré-exécution des outils et analyse post-génération des scripts/documents |
| `agent_protocol.py` | Conversion UI/base vers Ollama et encodage JSON des événements SSE |
| `agent_routing.py` | Inventaire Ollama, sélection de profil et détection du contexte sensible |
| `agent_tool_selection.py` | Matrice d'outils, routage sémantique, repli borné et plafond déterministe |
| `agent_execution.py` | Frontière LLM/actions : registre injectable, reçus idempotents, erreurs et normalisation des appels textuels |
| `agent_review.py` | Revue indépendante injectable des réponses techniques et des actions sensibles |
| `agent_context.py` | Compaction du contexte de session et cycle de vie des captures multimodales |
| `agent_session.py` | Création/reprise du tour, persistance utilisateur, événements initiaux et titrage |
| `agent_planning.py` | Plan déterministe pré-LLM : intentions, Workspace, contraintes Cortex et budgets |
| `agent_model_config.py` | Configuration typée du modèle, confidentialité, température, label et repli local |
| `agent_runner.py` | État observable du run : budget, outils, traces, blocages et résultat |
| `agent_observability.py` | Diffusion isolée des observations d'outils vers audit, SQLite, preuves et apprentissage |
| `agent_skill_outcome.py` | Issue idempotente des compétences, golden path et auto-amélioration suivie |
| `agent_council_escalation.py` | Arbitrage Council borné après désaccord explicite du vérificateur |
| `agent_learning.py` | Apprentissage post-réponse résident ou dédié et suivi anti-GC |
| `agent_turn_context.py` | Fenêtre d'historique, chemins, permissions et enrichissements persistants du prompt |
| `agent_enrichment.py` | Tâches concurrentes de rappel, matching et sélection d'outils avec annulation structurée |
| `agent_skill_context.py` | Méthode Markdown, golden path et ressources d'une compétence validée |
| `agent_model_step.py` | Lecture typée d'une itération Ollama et matérialisation des appels contractuels |
| `agent_tool_batch.py` | Exécution séquentielle, événements, preuves et persistance d'un lot d'outils |
| `agent_turn_completion.py` | Sortie commune : revue, persistance, apprentissage, skill et provenance |
| `agent_loop_policy.py` | Politiques inter-itérations : repli sensible, relance Skill et refus Forge |
| `agent_budget_completion.py` | Synthèse terminale sans outil et repli utilisateur lors d'un budget épuisé |
| `agent_transport.py` | Client HTTP Ollama, payload `/api/chat`, décodage JSONL et erreurs de transport typées |
| `document_formatting.py` | Projection Markdown commune aux générateurs DOCX/PDF et échappement ReportLab |
| `document_profile.py` | Identité persistante, champs autorisés et catalogue de modèles documentaires |
| `action_replay.py` | Reçus transactionnels et déduplication des actions à effet de bord d'un tour chat |
| `chat_turn_runtime.py` | Producteurs de tours détachés, journal SSE durable, curseurs de reconnexion et reprise sûre |
| `proactive_briefing.py` | Agrégation concurrente et observable des tâches, événements et boîtes pour le briefing |
| `intent_guard.py` | Intentions déterministes avant LLM : aucun outil, commande texte, Council et Code Workspace |
| `tools.py` | Implémentations, registre et schémas des outils exposés au LLM |
| `tool_domains/` | Implémentations métier extraites (Fichiers, Documents/PDF, e-mails, documentation d'intervention, sécurité et contrôles opérationnels, santé client, Winget, registre/paramètres/tweaks/nettoyage Windows, Web, Réseau, Facturation, contrôle/diagnostic PC, Windows, Quiz, Base IT, Tâches/Notes, Mémoire, Média, SSH); `tools.py` conserve la façade et les contrats publics pendant la migration |
| `config.py` | Profils de modèles, ports et politiques de permission |
| `database.py` | Façade historique d'accès SQLite et compatibilité défensive des domaines métier |
| `email_account_service.py` | Résolution partagée des comptes e-mail, façade multi-comptes et projection publique sans secrets |
| `ssh_transport.py` | Chargement des clés privées et connexions Paramiko partagés entre API et outils |
| `api/video_remote.py` | Catalogue Replicate, génération texte/image, suivi SSE, annulation et import des vidéos distantes |
| `api/video_editing.py` | Diaporamas, animations texte, stockage borné et montage ffmpeg local hors de la boucle asyncio |
| `api/video_local.py` | Capacités GPU, génération Diffusers texte/image, annulation et amélioration de prompt Ollama |
| `db_connection.py` | Fabrique de connexions WAL, clés étrangères et frontière commit/rollback |
| `db_migrations.py` | Catalogue de schéma versionné, checksums, compatibilité et rollback transactionnel |
| `repositories/` | Persistance métier injectable; conversations/messages, connexions SSH et workflows extraits |
| `skills.py` | Compétences Markdown, matching, apprentissage et versioning |
| `tool_router.py` | Index sémantique et sélection dynamique des outils |
| `cortex.py` | Contrats de mission, budgets adaptatifs, routage explicable, provenance et recettes Cortex |
| `cortex_search.py` | Exploration multi-stratégies, vérificateurs spécialisés et arbitrage Cloud |
| `forge.py` | Corpus de scénarios, notation déterministe, historique et métriques pass^k |
| `mission_os.py` | Missions durables, checkpoints, journal d'événements et preuves d'actions |
| `memory_mesh.py` | Métadonnées cognitives working, episodic, semantic et procedural |
| `truth_ledger.py` | Registre append-only des affirmations, sources et niveaux de preuve |
| `auto_config.py` | Adaptation des modèles et capacités au matériel |
| `cloud_routing.py` | Cloud facultatif, sélection par capacité et repli local |
| `model_market.py` | Catalogue dynamique, observations passives et classement des modèles cloud |
| `research_swarm.py` | Recherche web parallèle, contradiction, vérification et synthèse sourcée |
| `swarm_jobs.py` | Exécutions Research Swarm persistantes, annulables et reprenables |
| `evolution_lab.py` | Expériences bornées, comparaison baseline/candidate, promotion et rollback |
| `vector_store.py` | Embeddings et stockage Qdrant dans le processus backend |
| `doctor.py` | Diagnostics déterministes et réparations contrôlées |
| `app_version.py` | Source unique de la version publique |

## Responsabilités frontend

| Zone | Responsabilité |
|---|---|
| `app/` | Pages App Router et proxys Next.js compatibles avec l’UI historique |
| `lib/backend.js` | Résolution unique de l’URL FastAPI en local, LAN et SSR |
| `lib/chatStream.js` | Transport SSE reprenable, curseur `turnSeq` et reconnexion bornée sans doublon |
| `lib/contexts/ChatContext.jsx` | État global du chat et lecture du flux SSE |
| `components/chat/` | Saisie, rendu des messages, outils et fichiers |
| `components/sidebar/` | Navigation et état global visible |
| `lib/hooks/useVoice.js` | Capture, synthèse et mode vocal continu |

## Sources de vérité

- Version publique : `backend/app_version.py`.
- Données applicatives : backend Python et `data/secretary.db`.
- Outils disponibles : `TOOLS_REGISTRY` et `TOOLS_SPEC`, obligatoirement identiques.
- URL backend côté JavaScript : `lib/backend.js`.
- Historique fonctionnel fin : commentaires `# vX.Y` de `backend/main.py` et Git.
- État d'exécution des workers : `app.state.runtime_supervisor`.

Le résumé non sensible des workers est exposé dans `/api/health` (`total` et compte par
statut). Les messages d'exception complets restent internes au processus et aux journaux afin
de ne pas exposer accidentellement des données dans une réponse HTTP.

## Invariants automatisés

`scripts/check_architecture.py` fonctionne sans importer le backend et contrôle :

1. l’alignement des versions Python, npm et lockfile ;
2. l’égalité exacte entre registre et schémas des outils ;
3. l’absence de doublons d’outils et de routes ;
4. la validité des listes de permissions ;
5. la couverture des pages par le smoke test Playwright ;
6. l’absence de nouvelle URL FastAPI codée en dur dans le frontend ;
7. le montage de chaque module `api/*.py` et l’absence de route dupliquée après extraction ;
8. le contrat idempotent du superviseur des workers ;
9. l'idempotence, l'intégrité et le rollback des migrations SQLite sur une base temporaire ;
10. le démarrage de l'initialiseur Next.js sur une base vierge ;
11. les reçus d'action : déduplication, concurrence, interruption et masquage des secrets ;
12. les tours de chat détachables : journal durable, curseur, reconnexion et arrêt sûr.
13. la frontière d'exécution agentique : registre, reçus, erreurs et appels textuels bornés.
14. la revue indépendante : déclenchement, modèle distinct, constats substantiels et repli sûr.
15. le contexte agentique : cache de compaction, confinement et nettoyage des captures.
16. la préparation de session : création, idempotence du message, captures, titre et tâches suivies.
17. le plan de tour : suppression et obligation d'outils, reprise Workspace et budgets Cortex.
18. la configuration modèle : routage auto/manuel, contrats local/cloud et repli sensible.
19. l'état du Runner : progression, arrêt, preuves d'outils, blocages Forge et provenance.
20. l'observabilité du Runner : une panne de métrique, preuve ou apprentissage ne peut pas invalider une action exécutée.
21. le transport Ollama : payload, timeouts, JSONL et erreurs restent indépendants du Runner et du SSE frontend.
22. les domaines d'outils : chaque extraction préserve l'identité des fonctions du registre et l'égalité stricte des 363 implémentations/spécifications.
23. le routeur SSH : toutes les routes HTTP, SSE, WebSocket et SFTP appartiennent exclusivement à `api/ssh.py`; aucune copie de fonction ne subsiste dans `main.py`.
24. les comptes e-mail : configuration, liste, ajout, retrait et test appartiennent à `api/email_accounts.py`; la résolution OAuth/mot de passe passe par un service partagé.
25. la boîte e-mail : lecture/recherche/dossiers, envoi audité, mutations et pièces jointes appartiennent à `api/email_mailbox.py` et utilisent la même résolution multi-comptes.
26. les préférences e-mail : signatures, modèles, surveillance, alertes et règles appartiennent à `api/email_preferences.py`; leurs exécutions restent déléguées au registre d'outils.
27. l'IA e-mail : brouillons, résumés, digest, profils, scheduler, drafts et outbox appartiennent à `api/email_automation.py`; l'activation initiale exige une confirmation explicite.
28. la vidéo distante : modèles, générations texte/image, suivi SSE, annulation et import Replicate appartiennent à `api/video_remote.py`; le jeton reste lu par le gestionnaire de secrets.
29. le montage vidéo local : diaporamas, texte animé, fichiers et opérations ffmpeg appartiennent à `api/video_editing.py`; tout nom de fichier reste confiné au stockage vidéo.
30. la génération vidéo IA locale : capacités, modèles, SSE texte/image, annulation et amélioration du prompt appartiennent à `api/video_local.py`; les fichiers uploadés sont nettoyés sur toute sortie du stream.
31. les outils média : les 11 actions vidéo/GIF et 6 actions audio appartiennent à `tool_domains/media.py`; la façade injecte son résolveur de chemins et préserve les 17 identités du registre.
32. le transport SSH : l'API et les outils utilisent `ssh_transport.py`; aucune route ne dépend d'un helper SSH privé de `tools.py`.
33. le domaine SSH : cibles, commandes, scripts et transferts appartiennent à `tool_domains/ssh.py`; `api/ssh.py` ne dépend plus de `tools.py` et les neuf identités du registre sont préservées.
34. la persistance SSH : CRUD, statut de test et dernier usage appartiennent à `repositories/ssh_connections.py`; les listes publiques excluent les secrets et toute opération passe par la transaction `db()`.
35. la persistance des workflows : définitions et exécutions appartiennent à `repositories/workflows.py`; les anciens JSON invalides se replient sur une liste vide, l'historique est borné et la suppression d'un workflow avec ses exécutions est atomique.
36. la finalisation agentique : scan déterministe, critique indépendante et escalade Council appartiennent à `agent_finalization.py`; les sorties normales et par budget partagent le même ordre d'événements SSE.
37. les outils obligatoires : `agent_required_tools.py` matérialise les contrats explicites sans doublon, préserve l'autonomie tant que le modèle agit et injecte le contexte du livrable précédent uniquement pour une reprise Code Workspace.
38. l'étape d'outil : `agent_tool_step.py` normalise les variantes d'arguments des modèles, injecte les identifiants internes hors du LLM et borne uniquement la projection de résultat renvoyée au contexte modèle.
39. le dispatch d'outil : `agent_tool_dispatch.py` applique anti-polling, outil explicite, texte sans exécution, validation des arguments, niveau Sécurisé et confirmation Expert avant l'exécuteur idempotent.
40. la post-validation d'outil : `agent_tool_postprocess.py` normalise le contrat de résultat, critique les confirmations dangereuses et inspecte le contenu documentaire sans invalider une action déjà exécutée si un observateur tombe en panne.
41. l'issue d'une compétence : `agent_skill_outcome.py` enregistre une seule issue par tour, conserve le golden path des succès et suit l'auto-amélioration asynchrone d'un véritable échec d'outil.
42. les effets post-réponse : `agent_council_escalation.py` n'autorise Council qu'après un désaccord et une politique explicite; `agent_learning.py` choisit la stratégie résidente ou dédiée et conserve toute tâche jusqu'à sa fin.
43. le contexte de tour : `agent_turn_context.py` prépare l'historique, les chemins réels, les permissions, les mémoires, les contraintes Cortex, le projet et l'identité documentaire avec des replis déterministes.
44. les enrichissements du tour : `agent_enrichment.py` isole rappel, matching et catalogue, absorbe leurs pannes indépendantes et annule toute tâche restante lors d'une sortie anticipée; `agent_skill_context.py` refuse une compétence incomplète sans casser le chat.
45. l'itération modèle : `agent_model_step.py` projette thinking et texte, collecte les appels natifs, récupère les appels textuels et matérialise les outils requis avant toute exécution.
46. le lot d'outils : `agent_tool_batch.py` conserve l'ordre dispatch, post-validation, `tool_end`, état Runner, observabilité, contexte Ollama et persistance; une panne d'observation ne transforme jamais l'action exécutée en échec.
47. la sortie du tour : `agent_turn_completion.py` impose le même ordre de revue, persistance, issue de compétence, recette Cortex, provenance et `done` aux terminaisons normales et par budget; l'apprentissage reste désactivé pour une synthèse incomplète par budget.
48. les archives : `tool_domains/archives.py` crée les ZIP de façon atomique et extrait ZIP/TAR membre par membre; chemins absolus ou traversants, liens, fichiers spéciaux et décompressions hors limites sont refusés avant écriture.
49. les tableurs : `tool_domains/spreadsheets.py` possède création et lecture XLSX ainsi que les conversions CSV; les sorties sont atomiques, les CSV traités en flux borné et les classeurs fermés sur toute sortie.
50. l'OCR vision : `tool_domains/ocr.py` conserve le routage Cloud/local de confidentialité, borne et valide l'image avant encodage et isole le transport Ollama derrière une interface injectable.
51. les captures documentaires : `tool_domains/screenshots.py` analyse les images selon le profil de confidentialité, projette l'index SQLite et compose DOCX/PDF; `agent_context.py` dépend directement de ce domaine et non de la façade globale `tools.py`.
52. les images locales : `tool_domains/images.py` possède inspection, resize, crop, rotation, compression, PDF et lots; orientation EXIF, limites de pixels/fichiers, paramètres et sorties atomiques sont uniformes.
53. le noyau PDF : `tool_domains/pdf_core.py` possède lecture, métadonnées, fusion, découpage et rotation; sélections de pages, volumes, chiffrement et écritures atomiques sont gérés sans dépendance aux moteurs OCR/rendu.
54. le PDF avancé : `tool_domains/pdf_advanced.py` possède filigrane, protection AES, extraction/rendu d'images, OCR, AcroForm, compression et numérotation; les transports et réglages OCR sont injectés, les dépendances optionnelles restent confinées.
55. la connaissance documentaire : `tool_domains/document_knowledge.py` possède extraction multi-format, indexation Qdrant, Q/R RAG, inventaire, oubli et affinage de section; le magasin vectoriel reste injecté depuis le processus backend et les documents générés sont confinés par relation de chemin.
56. la documentation d'intervention : `tool_domains/intervention_docs.py` possède le CRUD d'interventions, l'analyse de notes, les livrables ITIL, les actifs et la recherche historique; les générateurs DOCX/PDF et l'analyse de commandes sont injectés, les formats et volumes sont validés.
57. la sécurité des commandes : `tool_domains/command_safety.py` extrait les commandes, détecte leur plateforme, applique les règles de risque et trace les approbations sans jamais exécuter la commande; entrées et volumes sont bornés.
58. les contrôles opérationnels : `tool_domains/operations_safety.py` possède les modèles et exécutions déclaratives de pré/post-checks, les preuves et leur rapport; le type de checklist, les statuts, les lots et les formats sont contrôlés avant persistance.
59. la santé client : `tool_domains/client_health.py` agrège documentation, actifs, incidents, commandes et sauvegardes en scores et recommandations, puis produit historique et synthèse mensuelle; limites, statuts et formats sont explicites.
60. Winget : `tool_domains/winget.py` possède découverte, parsing, recherche, inventaire et mutations non interactives; limites, sources et identifiants sont validés, et toute mutation reste confirmée.
61. les paramètres Windows : `tool_domains/windows_settings.py` possède alimentation, thème, pare-feu, cartes réseau et hibernation; le transport PowerShell est injecté et les valeurs composées dans un script sont validées avant exécution confirmée.
62. le registre Windows : `tool_domains/windows_registry.py` possède point de restauration, lecture, export et écriture; chemins, noms, types et valeurs sont validés/encodés avant PowerShell, avec sauvegarde et confirmation sur mutation.
63. les tweaks Windows : `tool_domains/windows_tweaks.py` possède télémétrie, débloat et réglages réseau; les dépendances registre sont injectées et le retrait UWP est limité au catalogue exact présenté par Marvin.
64. Catharsis : `tool_domains/catharsis.py` possède scan et purge des caches; catégories et projections sont limitées au catalogue interne, les valeurs invalides sont neutralisées et toute suppression reste confirmée.
65. la recherche Windows : `tool_domains/system_search.py` possède les requêtes par nom et
contenu sur l'index Windows Search; limites et types sont bornés, les littéraux sont échappés
et la durée COM est exécutée hors de la boucle asyncio.
66. l'ITSM : `tool_domains/itsm.py` possède le transport GLPI, les tickets et les actifs;
sessions distantes, entrées, limites et confirmation des créations sont gérées par le domaine.
67. l'observabilité runtime : `tool_domains/runtime_observability.py` possède les journaux de
bugs et d'apprentissage; filtres, volumes et projections sont contrôlés avant exposition au LLM.
68. Google Drive : `tool_domains/google_drive.py` possède OAuth, liste, export et upload; les
appels SDK sont hors boucle asyncio, les entrées sont bornées et les flux fichiers sont fermés.
69. OneDrive : `tool_domains/onedrive.py` possède OAuth Microsoft et les appels Graph; lecture,
chemins, tailles et upload simple en flux sont bornés selon les contrats du fournisseur.
70. Google Calendar : `tool_domains/google_calendar.py` possède authentification, résolution
d'agenda, dates et CRUD distant; appels SDK, repli OAuth et durée des événements sont isolés.
71. les abonnements calendrier : `tool_domains/calendar_subscriptions.py` possède stockage,
iCalendar récurrent, import Google et synchronisation; secrets, SSRF et volumes sont encadrés.
72. les événements agenda : `tool_domains/calendar_events.py` possède parsing temporel,
CRUD local et routage Google. Il refuse les intervalles invalides, les replis silencieux et
les suppressions ambiguës. `agent_safety.py` valide les valeurs déclarées par les schémas de
tous les outils avant le dispatch du Runner.
73. les utilitaires déterministes : `tool_domains/deterministic_utilities.py` possède calcul,
génération de mots de passe, empreintes, Base64, JSON et statistiques textuelles. Entrées,
profondeur, complexité, sorties et opérations coûteuses sont bornées; aucun `eval` n'est utilisé.
74. le gateway d'outils : `tool_gateway.py` applique le même cœur déterministe aux appels du
chat, de l'interface et de MCP. Le catalogue `/api/tools/list` expose couverture, écarts,
    couches et restrictions; `check_architecture.py` interdit une couverture inférieure à 363/363.
75. les contrats d'outils fermés : les 363 schémas racine déclarent
`additionalProperties=false`. Un champ halluciné ou mal orthographié est refusé avant
permission, confirmation et effet de bord.
76. la date et l'heure : `tool_domains/datetime_tools.py` possède horloge, parsing ISO,
fuseaux IANA, différences et deltas. Les dates naïves conservent la convention UTC historique;
les fuseaux inconnus et les deltas non bornés sont refusés explicitement.
77. les conversions d'unités : `tool_domains/unit_conversion.py` possède facteurs,
dimensions, alias et températures. Les calculs intermédiaires sont décimaux et finis;
incompatibilités, valeurs extrêmes et températures physiquement impossibles sont refusées.
78. la météo : `tool_domains/weather.py` possède géocodage et prévisions Open-Meteo.
Transport et cache TTL sont injectés depuis la façade Web; paramètres, coordonnées et
structures distantes sont contrôlés avant projection vers le Runner.
79. la traduction : `tool_domains/translation.py` reçoit le générateur Ollama commun.
Le routeur de confidentialité choisit local/cloud, le modèle réellement exécuté est remonté
par le transport, et le contenu à traduire ne dispose d'aucun outil ni effet de bord.
80. le traitement textuel : `tool_domains/text_processing.py` possède extraction, diff,
Markdown, regex et jointure. Les opérations coûteuses quittent la boucle asyncio, les sorties
sont bornées, le rendu HTML échappe les données non fiables et le moteur `regex` interrompt
les motifs pathologiques. Le validateur central applique les bornes de chaînes et de listes
déclarées dans les schémas avant l'exécution.
81. les données structurées : `tool_domains/structured_data.py` possède analyse CSV,
graphiques PNG et inspection/requête SQLite. Le CSV est lu en flux borné; Matplotlib utilise
une `Figure` isolée et une sortie atomique. L'authorizer SQLite détecte les mutations réelles,
y compris derrière une CTE, refuse les capacités hors périmètre et exige confirmation.
Une écriture confirmée dispose d'une sauvegarde cohérente avant commit.
82. les documents Office : `tool_domains/presentations.py` possède création et lecture PPTX;
`tool_domains/documents.py` possède aussi l'extraction DOCX. `office_packages.py` valide les
conteneurs Open XML avant parsing. Les sorties sont atomiques, les volumes bornés et
`Document.iter_inner_content()` préserve l'ordre réel entre paragraphes et tableaux.
83. les formats locaux déterministes : `tool_domains/images.py` possède aussi la génération
QR PNG atomique; `tool_domains/archives.py` possède l'inventaire ZIP borné avec contrôle CRC;
`tool_domains/deterministic_utilities.py` possède la conversion stricte HEX/RGB/HSL. Les
façades historiques et les entrées du registre restent identiques.
84. l'analyse avancée des fichiers : `tool_domains/filesystem.py` possède la recherche des
gros fichiers, la lecture en lot et la détection de doublons. Les parcours sont bornés et
sans suivi des liens; les lectures sont déportées et les doublons exigent un SHA-256 complet.
85. le renommage transactionnel : `tool_domains/filesystem.py` possède `bulk_rename`.
Validation et collisions précèdent tout effet; une permutation passe par des noms temporaires
du même dossier. Le manifeste atomique permet un rollback explicite, idempotent et capable
de reprendre un état intermédiaire après interruption.
86. l'egress HTTP public : `outbound_http.py` centralise validation de schéma/port,
résolution DNS publique, épinglage IP/SNI, redirections manuelles revalidées et budgets.
`web_browse` et `url_analyze` passent par ce guardrail; aucune redirection automatique ne
peut les faire basculer vers localhost, une adresse privée ou un service de métadonnées.
87. les inspections Git et IP : `tool_domains/git_repository.py` exécute quatre commandes
Git de lecture à arguments fixes, sans shell, avec formats stables, délai et sorties bornés.
`tool_domains/network.py` possède `ip_info`, qui valide les adresses globales puis appelle
IPWhois en HTTPS à travers `outbound_http`; l'ancien transport HTTP non chiffré est supprimé.
88. le nettoyage système : `tool_domains/system_cleanup.py` possède le scan et la suppression
confirmée des seuls fichiers temporaires assez anciens. Racines dédupliquées, liens ignorés,
parcours borné, opérations bloquantes hors event loop et erreurs visibles remplacent le
parcours illimité qui masquait les échecs.
89. le moteur Council : `model_council.py` orchestre exactement cinq familles Ollama Cloud,
en parallèle borné, puis une critique anonymisée et un arbitrage. Le routage de confidentialité
reste déterministe; aucun repli local n'est possible. Chaque exécution porte un `council_id`,
les dépendances sont injectables et les volumes de contexte/réponse sont plafonnés.
90. les graphiques : `tool_domains/charts.py` possède les onze rendus
`infographic_create`. Chaque rendu utilise une `Figure` isolée, valide les dimensions,
séries, nombres finis et couleurs, quitte la boucle asyncio et publie le PNG par remplacement
atomique. La façade ne dépend plus de l'état global Matplotlib.
91. l'exécution Python rapide : `python_execution.py` isole le processus et son environnement,
borne code, temps, sorties et artefacts, puis termine l'arbre au timeout. Le contrat expose
explicitement l'absence de sandbox OS/réseau; les capacités hôte demandent confirmation.
Tout code non fiable ou à certifier doit passer par Test Forge et son conteneur/sa VM.
92. les tâches longues : `tool_domains/long_tasks.py` injecte base, Mission OS et génération.
Le démarrage compense les tâches déjà écrites si le cron échoue, chaque tag est unique et les
erreurs de synchronisation restent observables. L'arrêt désactive la reprise sans supprimer
la checklist, ce qui préserve l'audit et fournit un rollback métier explicite.
93. l'auto-diagnostic : `tool_domains/system_self_test.py` possède un catalogue explicite de
sondes sans mutation, un ordre de rapport déterministe, une concurrence de quatre et un délai
d'attente individuel. Les dépendances réseau sont classées séparément; erreurs, absences,
crashs et timeouts ne sont plus confondus.
94. la recherche unifiée : `tool_domains/unified_search.py` fédère documents, fichiers, notes,
tâches, événements, mémoire, e-mails et Web derrière neuf dépendances injectées. Les scopes,
limites, concurrence et délais sont bornés; chaque source produit une provenance explicite et
les pannes partielles ne sont plus masquées.
95. le raisonnement parallèle : `parallel_reasoning.py` orchestre décomposition, travaux LLM
sans outils et synthèse. Les volumes sont bornés, une trace identifie le pipeline et les échecs
partiels ou de synthèse conservent les résultats intermédiaires. Cette frontière ne revendique
pas les capacités de la boucle Runner outillée.
96. l'OCR écran : `tool_domains/screen_ocr.py` capture et redimensionne hors de la boucle,
applique vision puis Tesseract selon une méthode validée et expose modèle, Cloud et tentatives.
Pixels, prompt et texte sont bornés; le temporaire est toujours supprimé et une capture
conservée est publiée atomiquement avec rollback.
97. la transcription locale : `voice_transcription.py` fournit à l'API et à l'outil agentique
un cache Whisper LRU commun limité à deux modèles, un verrou de chargement et un verrou
d'inférence par modèle. Formats, taille, langue, modèle et texte sont bornés; l'upload HTTP
est écrit par blocs et le repli vers `base` reste explicitement visible.
98. le runtime Web : `web_runtime.py` possède le pool `httpx.AsyncClient`, sa fermeture et le
cache TTL/LRU partagé par Web et Météo. La création est sérialisée, la fermeture intervient
après les workers, les entrées sont bornées et copiées défensivement, et les erreurs hors ligne
conservent le contrat historique.
99. l'automatisation e-mail : `tool_domains/email_automation.py` possède le traitement
multiboîte et la file d'envoi différé. Les transports, réglages et actions de rédaction/envoi
sont injectés; round-robin, idempotence, simulation sans écriture, anti-boucle, plafonds,
retries et exclusion mutuelle sont testables sans réseau.
La façade `tools.py` ne conserve aucun second corps d'automatisation e-mail : configuration,
orchestrateur et flush sont des alias directs vers cette frontière.
100. les messages e-mail : `tool_domains/email_messages.py` possède la projection publique
des comptes, lecture, recherche, envoi confirmé, rédaction, résumé et briefing. Les transports
et le générateur sont injectés; les opérations IMAP/SMTP sortent de la boucle asyncio, les
entrées et sorties sont bornées et une panne d'une boîte ne supprime pas le briefing des autres.
Les huit exécuteurs historiques sont des alias directs; OAuth et les secrets restent résolus
par `email_accounts` sans être exposés au modèle.
101. la productivité e-mail : `tool_domains/email_productivity.py` transforme un message en
tâche structurée et résume les pièces jointes autorisées. Le parsing JSON, les priorités,
dates, tailles, extensions, textes et sorties sont bornés. IMAP et les écritures temporaires
quittent la boucle asyncio; les fichiers intermédiaires sont supprimés dans tous les chemins.
Les créations de tâches passent encore par le domaine Productivity et les lecteurs de
documents existants, sans dupliquer leur logique.
102. la surveillance e-mail : `tool_domains/email_monitoring.py` possède la collecte des
non-lus, leur classification IA par lots, les alertes et l'application des règles. Un lot non
classifié n'est pas inscrit dans l'état `seen`, afin d'être repris au passage suivant. Les
règles n'acceptent que déplacement, lecture ou non-lecture; volumes, comptes et dossiers sont
bornés, les simulations n'effectuent aucune mutation distante et toutes les pannes partielles
sont projetées dans le résultat.
103. le briefing proactif : `proactive_briefing.py` agrège tâches, agenda et boîtes IMAP avec
des dépendances injectées. Les trois familles de sources s'exécutent en parallèle, les boîtes
avec une concurrence de quatre; chaque statut contient quantité, durée ou erreur. Une source
défaillante produit un résultat partiel explicite, sans effacer les données disponibles, et
aucune lecture SQLite ou IMAP ne bloque la boucle asyncio.

Toute lecture ou écriture SQLite applicative doit utiliser `with database.db()` ou un
repository. `scripts/test_db_connection_hygiene.py` refuse les appels directs à `get_conn()`
hors de `db_connection.py`, afin que fermeture, commit et rollback restent systématiques.

`scripts/check_marvin.py` orchestre ces invariants avec le contrôle du runtime, des
dépendances, de la compilation et du frontend. En mode `--live`, tous les contrôles backend
passent par HTTP : aucun second processus ne tente d’ouvrir le stockage Qdrant local.

## Règles d’évolution

- Ne jamais ouvrir Qdrant depuis un second processus Python.
- Ne pas déplacer la logique métier vers les routes Next.js : FastAPI reste la source de vérité.
- Une compétence reste du Markdown injecté au prompt, jamais du code exécutable.
- Toute action sortante ou irréversible conserve son mécanisme de confirmation.
- Les extractions futures de `main.py` et `tools.py` doivent se faire domaine par domaine,
  avec compatibilité d’import et contrôles verts avant chaque étape.
