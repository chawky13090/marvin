# Plan de consolidation complète du backend Marvin

> Ce plan spécialisé reste applicable au backend. Le contrat transversal
> `MARVIN-FRONTIER-CONSOLIDATION.md` couvre désormais l'intégralité du produit et prévaut
> pour les exigences de preuve, de comparaison, de test et de rollback.

Date de référence : 2026-07-28
Version auditée : 2.411.0
Périmètre : backend Python, contrats FastAPI, Runner agentique, outils, persistance,
workers, observabilité et validation. Le frontend est explicitement hors périmètre tant que
les critères de clôture ci-dessous ne sont pas satisfaits.

## 1. Décision d'architecture

Marvin reste un monolithe modulaire. Il n'est pas transformé en microservices : le besoin réel
est un assistant Windows installable, local-first et exploitable sur une seule machine. La
séparation recherchée concerne les responsabilités du code, pas les processus de déploiement.

Deux approches ont été comparées :

1. réécriture globale de `agent.py`, `tools.py` et `database.py` ;
2. extraction progressive derrière les façades existantes, avec identité des fonctions,
   contrats HTTP, schéma SQLite et formats SSE conservés.

L'approche 2 est retenue. Elle minimise le risque de régression, permet un rollback par commit
et maintient Marvin utilisable entre chaque tranche.

Les références officielles convergent sur les mêmes primitives : Runner explicite, outils
documentés et spécialisés, état durable, guardrails déterministes, traces, évaluations et
choix du workflow le plus simple adapté au besoin. Marvin possède déjà ces primitives ; le
travail restant consiste à rendre leurs frontières de code aussi nettes que leurs contrats.

## 2. État établi

### Terminé et couvert par des tests

- protocole messages/Ollama/SSE ;
- routage des modèles et confidentialité cloud/local ;
- prompt système ;
- sélection déterministe et bornée des outils ;
- exécution des outils, reçus idempotents et reprise sûre ;
- revue indépendante ;
- contexte, préparation de session et plan de tour ;
- configuration modèle ;
- état observable du Runner et effets d'observabilité ;
- transport Ollama ;
- tours de chat détachables et reconnexion SSE ;
- workers idempotents, cron et reprises longues ;
- migrations SQLite transactionnelles ;
- repositories conversations, connexions SSH et workflows ;
- frontières API e-mail, vidéo et SSH ;
- domaines d'outils Productivité, Mémoire, Média, SSH, Quiz et Base IT ;
- 344 implémentations pour 344 spécifications et 354 routes sans doublon.

### Partiel

| Frontière | État mesuré | Reste |
|---|---:|---|
| Runner | Terminé en v2.313 : `agent.py` orchestre des frontières nommées | surveiller les régressions via les tests de contrat |
| Outils | `tools.py` : 20 197 lignes, 398 objets AST | extraire les domaines restants puis séparer catalogue et assemblage du registre |
| Persistance | `database.py` : 2 508 lignes, 96 objets AST | déplacer les domaines restants vers des repositories injectables |
| Composition FastAPI | `main.py` : 276 lignes, 47 routeurs, 2 fonctions actives | terminé en v2.403 : composition, imports et lifespan couverts par contrat |
| Dépendances | nombreux imports directs de `tools` et `database` | remplacer progressivement par services/domaines, sans rupture de façade |

## 3. Ordre d'exécution

### Phase A — Runner

1. extraire la préparation de boucle et la projection des événements ;
2. extraire la gestion d'un appel modèle et d'une étape d'outil ;
3. extraire la finalisation normale, budget épuisé et erreur ;
4. conserver `run_agent` comme orchestrateur lisible ;
5. tester chaque sortie SSE, reprise, budget, revue, compétence et observabilité.

Critère : `run_agent` orchestre des composants nommés et ne contient plus une boucle métier
monolithique. Aucun événement SSE ni comportement de modèle ne change.

État : **terminé en v2.313.0**. La session, le plan, le contexte, les enrichissements, la
configuration modèle, le transport, une itération modèle, un lot d'outils, les politiques
inter-itérations et les deux sorties terminales ont chacun une frontière testable. Le Runner
central ne contient plus d'implémentation métier d'outil, de persistance ou de revue.

### Phase B — Outils

Extraire par cohésion et risque :

1. fichiers et documents ;
2. PC et Windows ;
3. web, recherche et navigateurs ;
4. réseau et diagnostics ;
5. calendrier, cloud et connecteurs ;
6. données, PDF, tableurs et archives ;
7. facturation, documentation technique et opérations ;
8. utilitaires restants.

Chaque domaine conserve les mêmes objets fonctions dans `TOOLS_REGISTRY`. À la fin, séparer
les spécifications déclaratives du registre d'exécution.

État : mutations livrées en v2.314.0, inventaire et métadonnées en v2.315.0, lecture
multi-format en v2.316.0, recherche par nom en v2.317.0 et recherche de contenu en v2.318.0.
`tool_domains/filesystem.py` possède désormais onze outils; la génération documentaire reste
à extraire dans les tranches suivantes.

Le formatage Markdown partagé des documents est extrait en v2.319.0; les générateurs DOCX/PDF
gardent ainsi une seule grammaire avant leur déplacement vers le domaine documentaire.
L'identité persistante et le catalogue de modèles rejoignent `document_profile.py` en
v2.320.0, sans changer les façades consommées par l'API et les générateurs.
La création DOCX et les conversions DOCX/PDF rejoignent `tool_domains/documents.py` en
v2.321.0. La génération IA orchestrée rejoint le même domaine en v2.322.0 avec transport et
dossier injectés. Le générateur PDF natif rejoint cette frontière en v2.323.0; la chaîne
principale Fichiers/Documents est désormais extraite. Les archives ZIP/TAR rejoignent
`tool_domains/archives.py` en v2.324.0 avec extraction confinée et bornée; tableurs, OCR et
captures restent les prochains outils spécialisés à isoler. Création/lecture XLSX et
conversions CSV rejoignent `tool_domains/spreadsheets.py` en v2.325.0; OCR et captures sont
désormais les prochaines frontières Fichiers/Documents. L'OCR vision rejoint
`tool_domains/ocr.py` en v2.326.0 avec routage de confidentialité inchangé, validation des
images et transport testable; les captures documentaires terminent cette sous-phase.
Analyse, consultation et génération DOCX/PDF depuis les captures rejoignent
`tool_domains/screenshots.py` en v2.327.0. `agent_context.py` ne dépend plus de `tools.py`;
la sous-phase Fichiers/Documents est close et la suite porte sur les autres domaines d'outils.
Les sept opérations d'images locales rejoignent `tool_domains/images.py` en v2.328.0 avec
sorties atomiques, orientation EXIF et bornes uniformes. Les autres familles métier sont
extraites par cohésion avant la séparation finale registre/catalogue.
Le noyau pypdf (lecture, informations, fusion, découpage et rotation) rejoint
`tool_domains/pdf_core.py` en v2.329.0. Les traitements PDF avancés et l'OCR restent une
frontière distincte afin de ne pas coupler le noyau aux dépendances ReportLab/pdfium/Ollama.
Les neuf traitements avancés rejoignent `tool_domains/pdf_advanced.py` en v2.330.0 avec
transport OCR et réglages injectés. La famille PDF est close : `tools.py` ne contient plus
aucun corps `execute_pdf_*`, seulement les alias compatibles et les spécifications publiques.
Indexation documentaire, Q/R sourcée, inventaire, oubli et affinage rejoignent
`tool_domains/document_knowledge.py` en v2.331.0. Le magasin vectoriel partagé est injecté
depuis le processus backend afin de préserver le verrou Qdrant mono-process.
Les 19 outils Réseau rejoignent `tool_domains/network.py` en v2.332.0. Diagnostics passifs,
scans actifs bornés, TLS/SNMP, topologie et inventaire partagent désormais une frontière
explicite; la configuration Windows est injectée et les identités publiques restent stables.
Les 22 outils Facturation rejoignent `tool_domains/billing.py` en v2.333.0. Les transports
web/PDF sont injectés, les montants et paiements sont validés et le registre reste inchangé.
Les 14 outils Windows rejoignent `tool_domains/windows.py` en v2.334.0. Le runner PowerShell
est injecté, les actions de service restent confirmées et les journaux utilisent une liste
blanche afin qu'aucune entrée utilisateur ne devienne du code PowerShell.
Les cinq outils Web rejoignent `tool_domains/web.py` en v2.335.0. Génération, réglages et
transport HTTP/cache sont injectés; recherche simple, navigateur et Deep Research conservent
leurs contrats tandis que providers et volumes sont bornés.
Les 21 outils de contrôle PC rejoignent `tool_domains/pc_control.py` en v2.336.0. Les actions
restent protégées par confirmation et `security`; chemins/formatage sont injectés et les
contrats d'entrée sont validés avant toute commande, interaction GUI ou terminaison.
Les 10 outils de diagnostic PC rejoignent `tool_domains/pc_diagnostics.py` en v2.337.0.
PowerShell et Web sont injectés dans un ordre explicite; métriques, tendances et observabilité
restent en lecture/persistance historique avec paramètres bornés.
Les 18 outils de documentation d'intervention rejoignent
`tool_domains/intervention_docs.py` en v2.338.0. CRUD, analyse de notes, rapports et procédures,
livrables ITIL, actifs et recherche historique partagent une frontière explicite. Les
générateurs et l'analyse de commandes sont injectés; formats et limites sont validés avant
accès aux transports ou à la persistance.
Les cinq outils de sécurité des commandes rejoignent `tool_domains/command_safety.py` en
v2.339.0. L'analyse demeure strictement statique; plateforme, risque, alternative,
approbation et historique sont isolés, avec listes et volumes bornés.
Les six outils de contrôles opérationnels rejoignent `tool_domains/operations_safety.py` en
v2.340.0. Les pré/post-checks sont typés avant écriture, preuves et formats sont validés, et
les générateurs documentaires sont injectés sans introduire d'exécution automatique.
Les cinq outils de santé client rejoignent `tool_domains/client_health.py` en v2.341.0.
Calcul multi-axes, recommandations, historique et synthèse mensuelle partagent une frontière
testable; formats, statuts et volumes sont bornés et les erreurs internes ne sont plus exposées.
Les six outils Winget rejoignent `tool_domains/winget.py` en v2.342.0. Résolution, parsing et
exécution non interactive sont isolés; limites, sources et identifiants sont validés afin
d'empêcher leur interprétation comme options CLI, sans modifier les confirmations mutantes.
Les cinq outils de paramètres Windows rejoignent `tool_domains/windows_settings.py` en
v2.343.0. Le transport est injecté, toutes les mutations restent confirmées et les noms de
cartes réseau sont validés avant composition PowerShell.
Les quatre outils registre/restauration rejoignent `tool_domains/windows_registry.py` en
v2.344.0. Chemins, noms, types et valeurs sont validés ou encodés avant PowerShell; sauvegarde
et confirmation restent obligatoires pour les écritures.
Les quatre tweaks Windows rejoignent `tool_domains/windows_tweaks.py` en v2.345.0. Le retrait
UWP est borné au catalogue exact et dédupliqué; télémétrie et réseau utilisent les dépendances
registre injectées et toutes les mutations restent confirmées.
Les deux outils Catharsis rejoignent `tool_domains/catharsis.py` en v2.346.0. Scan et purge
sont limités au catalogue interne, les résultats PowerShell sont filtrés et toute suppression
reste explicitement confirmée.

Critère : `tools.py` devient une façade et un composition root d'outils ; aucun domaine métier
volumineux n'y est implémenté. Le contrôle 344/344 reste exact.

### Phase C — Persistance

Extraire par agrégat transactionnel :

1. paramètres et configuration ;
2. tâches, notes et mémoires ;
3. événements et calendriers locaux ;
4. projets et artefacts ;
5. traces d'exécution et fiabilité ;
6. inventaire, snapshots, modèles et cron ;
7. facturation ;
8. documentation et opérations ;
9. règles de commande, approbations et santé ;
10. base IT et fiches de révision.

Critère : `database.py` devient une façade d'import compatible. Toute opération passe par
`db()` ou un repository injectable, avec fermeture, commit et rollback garantis.

État : la première frontière est extraite en v2.405.0. Les paramètres globaux rejoignent
`repositories/settings.py` derrière un repository injectable. La façade `database.py`
conserve exactement `get_setting` et `set_setting`; lectures, types JSON historiques,
paramètres SQL, fermeture et atomicité sont couverts sur une base temporaire réelle.
Mémoires, tâches et notes rejoignent trois repositories distincts en v2.406.0. Leurs quinze
identités publiques restent exposées par `database.py`; création, filtres, mises à jour,
suppression, décodage JSON dégradé et rollback sont exercés sur SQLite réel.
L'agenda local et les miroirs iCal/Google rejoignent `repositories/events.py` en v2.407.0.
Les neuf fonctions historiques, la migration défensive des anciennes tables, les rappels et
le remplacement atomique par source sont conservés et couverts sur SQLite réel.
Projets, captures documentaires et catalogue de logos rejoignent trois repositories
injectables en v2.408.0. Les neuf façades restent identiques; migration des instructions,
relation projet/conversation, création/relecture atomique et catalogues sont testés.
Les traces d'exécution et agrégats de fiabilité rejoignent
`repositories/executions.py` en v2.409.0. Corrélation, statistiques, fenêtres récentes,
pagination, migration et cinq façades sont conservées. Les nouvelles traces sont expurgées
avant persistance; les preuves métier restent dans leurs registres durables dédiés.
Inventaire réseau, snapshots système, modèles d'outils et tâches cron rejoignent quatre
repositories injectables en v2.410.0. Leurs quatorze façades restent identiques; transactions,
index, fenêtres bornées, listes blanches de mise à jour, JSON historique dégradé et rollback
sont couverts sur SQLite réel. `database.py` ne possède plus leurs schémas ni leur CRUD.
Clients, devis, catalogue, factures et contrats rejoignent `repositories/billing.py` en
v2.411.0. Les vingt façades sont conservées. Numérotation annuelle concurrente, totaux,
marges, TVA, échéances, paiements, filtres, cascade et rollback sont testés sur SQLite réel;
le défaut historique de contrat sans date de début est corrigé.

### Phase D — Composition et dépendances

1. extraire les derniers endpoints chat, outils/MCP et proactif ;
2. conserver `main.py` pour la création de l'application, le lifespan, le montage des routeurs
   et le handler global ;
3. supprimer les imports inversés entre API, outils et persistance ;
4. contrôler les cycles d'import et le temps d'import du backend.

La recherche Windows est isolée derrière une frontière injectable, sans modifier les
identités `system_search` et `system_search_content` du registre public.
Le connecteur ITSM est isolé avec transport injectable et fermeture garantie des sessions
GLPI; l'ajout d'un autre backend ne doit pas étendre la façade `tools.py`.
L'observabilité consommée par le LLM est isolée des producteurs de logs et injectée dans les
tests, afin qu'une donnée interne mal formée ne casse pas un tour agentique.
Google Drive dispose de sa propre frontière fournisseur; OneDrive conserve une frontière
distincte afin de ne pas masquer les différences OAuth, Graph et stratégies d'upload.
OneDrive est désormais isolé avec transport injectable et upload asynchrone en flux; les
fichiers au-delà du contrat simple de 250 Mo exigent explicitement une upload session future.
Google Calendar est isolé tout en gardant ses alias privés provisoires pour les routes de
connexion, Doctor et les outils d'agenda encore en cours d'extraction.
Les abonnements iCalendar sont isolés avec URLs publiques masquées, récupération HTTP bornée
et protection SSRF; les suppressions via LLM exigent une confirmation explicite.
Les événements locaux/Google sont isolés avec cohérence de cible : aucun échec distant ne
devient une mutation locale silencieuse. Le harness valide maintenant les types, enums,
bornes et structures déclarés par les 344 schémas; l'unification UI/MCP reste à achever.
Les utilitaires déterministes sont isolés avec limites de ressources, primitives
cryptographiques standard, décodage strict et calcul AST sans `eval`.
Le gateway commun relie chat, UI et MCP au cœur déterministe. La couverture est prouvée à
344/344; les 64 outils dangereux ou interdits en mode Sécurisé sont comptés séparément comme
restrictions renforcées et non comme totalité du harness.
Les 344 schémas racine sont fermés (`additionalProperties=false`) : les arguments inconnus
sont refusés avant exécution, sans retirer les paramètres valides existants.
La date et l'heure sont isolées dans un domaine déterministe avec dépendance `tzdata`
portable, fuseaux IANA explicites et deltas imbriqués strictement validés.
Les conversions d'unités sont isolées avec facteurs de référence documentés, calcul décimal,
compatibilité des dimensions et conservation de tous les alias publics historiques.
La météo Open-Meteo est isolée derrière le transport/cache Web commun, avec validation des
entrées et réponses distantes; elle ne possède plus de client HTTP ou cache global séparé.
La traduction est isolée derrière le routage Ollama commun : aucun fournisseur externe ne
contourne Hyper local, Ultra reste cloud-only et la provenance reflète le modèle exécuté.
Extraction, diff, Markdown, regex et jointure sont isolés dans un domaine textuel déterministe.
Les entrées/sorties sont bornées, le HTML est sûr par construction et les regex disposent
d'un timeout natif. Le guardrail partagé fait respecter les bornes textuelles et de listes
des schémas, au lieu de les laisser purement déclaratives.
Analyse CSV, graphiques et accès SQLite sont isolés dans un domaine de données structurées.
Les fichiers sont bornés, les graphiques sont atomiques et les requêtes SQLite ne reposent
plus sur un test lexical contournable : l'authorizer natif classe les effets réels. Toute
écriture confirmée crée une sauvegarde cohérente avant commit.
Création/lecture PowerPoint et extraction Word ont rejoint leurs domaines Office. Une
validation Open XML commune borne les archives avant parsing; les sorties sont atomiques et
l'extraction Word conserve l'ordre réel du document.
Génération QR, inventaire ZIP et conversion de couleurs ont rejoint les domaines Images,
Archives et Utilitaires déterministes. Les écritures sont atomiques, les archives sont
bornées et vérifiées, et les syntaxes de couleurs sont analysées par grammaires fermées.
Recherche des gros fichiers, lecture en lot et détection de doublons ont rejoint le domaine
Filesystem. Les parcours et sorties sont bornés, les liens ne sont pas suivis et SHA-256 du
contenu complet remplace le MD5 partiel pour éviter les faux doublons.
Le renommage en lot a rejoint Filesystem dans une transaction à deux phases. Un manifeste
atomique conserve anciennes, nouvelles et temporaires; le rollback sait restaurer un état
appliqué ou interrompu. Toute collision est refusée avant le premier renommage.
Les lectures HTTP publiques disposent d'une frontière anti-SSRF commune : résolution et IP
publique contrôlées, connexion épinglée, SNI préservé, ports/budgets bornés et redirections
revalidées. `web_browse` et `url_analyze` ne suivent plus automatiquement une destination.
Les inspections Git et IP quittent aussi la façade historique. Git reste strictement en
lecture seule, sans shell et avec sorties bornées; la géolocalisation IP utilise exclusivement
HTTPS et le transport anti-SSRF. Les identités publiques du registre restent inchangées.
Le nettoyage système rejoint une frontière dédiée : seules les racines temporaires internes
sont parcourues, sans suivi des liens et avec un plafond explicite. Le rapport sépare enfin
volume observé et volume récupérable selon l'âge; suppressions et erreurs sont comptabilisées.
Le Council cinq modèles quitte la façade pour `model_council.py`. La frontière expose un
workflow explicite panel parallèle → critique aveugle → arbitrage, avec cinq familles Cloud
distinctes, budgets, provenance, identifiant de trace et dépendances injectables. Les profils
Hyper local/sensibles restent bloqués et aucun repli local silencieux n'est introduit.
La génération d'infographies rejoint `tool_domains/charts.py`. Les onze types partagent une
validation stricte des dimensions et valeurs, un rendu `Figure` sans état global et une
publication PNG atomique. Les séries incohérentes et nombres non finis sont refusés avant I/O.
L'exécuteur `code_python` rejoint `python_execution.py`. La frontière ne qualifie plus `-I`
de sandbox : environnement minimal, sorties sur fichiers temporaires bornés, artefacts
plafonnés, AST et timeout protègent le mode rapide; Test Forge/VM reste la seule frontière
annoncée comme confinement système et réseau pour du code non fiable.
Les missions longues rejoignent `tool_domains/long_tasks.py`. Persistance, Mission OS et
génération sont injectés; objectifs, étapes et tags sont bornés. Une panne cron après création
partielle déclenche une compensation en ordre inverse, dont le résultat est exposé au lieu de
laisser une checklist orpheline.
L'auto-diagnostic rejoint `tool_domains/system_self_test.py`. Le catalogue sûr devient une
donnée explicite, les appels sont concurrents avec une borne de quatre, chaque attente possède
un timeout et le résultat distingue absence, erreur métier, crash et timeout. Le mode sans Web
exclut toutes les sondes qui exigent réellement Internet.
La recherche fédérée rejoint `tool_domains/unified_search.py`. Les neuf sources sont injectées,
les scopes et limites invalides sont refusés, `["all"]` est corrigé et les lectures SQLite
quittent la boucle asyncio. Une provenance par source expose durée, quantité, erreur ou timeout
avec concurrence et volumes bornés.
Le raisonnement parallèle rejoint `parallel_reasoning.py`. Cette frontière n'est pas présentée
comme un système de sous-agents outillés : elle décompose, exécute jusqu'à cinq raisonnements
LLM indépendants puis synthétise. Objectifs, résultats et contexte sont bornés; trace, partiels
et phase d'échec restent observables.
L'OCR écran rejoint `tool_domains/screen_ocr.py`. Capture, région, pixels, prompt et sortie
sont bornés; les opérations bloquantes quittent la boucle asyncio. Le routage vision conserve
le contrat local/Ultra Cloud et devient visible dans le résultat. Les échecs de vision et de
Tesseract ne sont plus masqués, et temporaire, sauvegarde atomique et rollback sont testés.
La transcription Whisper rejoint `voice_transcription.py`. L'API vocale et le registre
d'outils ne chargent plus deux copies concurrentes du modèle. Cache LRU, chargement,
inférences, limites et validation sont mutualisés; le streaming d'upload empêche une allocation
non bornée et chaque repli de modèle est observable.
Le pool HTTP et le cache Web rejoignent `web_runtime.py`. `tools.py` ne possède plus ces états
globaux; Web et Météo reçoivent toujours les mêmes façades. Le runtime garantit création
unique, fermeture après les workers, recréation, cache TTL/LRU borné et copies défensives.
L'orchestrateur e-mail multiboîte et la file différée rejoignent
`tool_domains/email_automation.py`. Les dépendances IMAP, rédaction, envoi et persistance sont
injectées; simulation, équité, anti-boucle, retries et exclusion mutuelle partagent désormais
un contrat déterministe.
La tranche de nettoyage v2.382 retire ensuite 440 lignes historiques de `tools.py`; les
workers, routes et registre utilisent exclusivement la frontière extraite.
La tranche v2.383 extrait ensuite les huit outils unitaires vers
`tool_domains/email_messages.py`. La façade conserve seulement la résolution des comptes et
l'injection des transports; consultation, envoi confirmé et assistance IA sont bornés,
non bloquants et testés en isolation. Une panne partielle lors d'un briefing multiboîte reste
observable sans supprimer les résultats disponibles.
La tranche v2.384 sépare les transformations productives dans
`tool_domains/email_productivity.py` : tâche structurée depuis un message et résumé de pièce
jointe. Les dépendances métier existantes restent injectées, le JSON et les dates sont
contrôlés, et les pièces jointes suivent une politique de taille, format et nettoyage
temporaire explicite.
La tranche v2.385 extrait la surveillance et les règles dans
`tool_domains/email_monitoring.py`. La classification couvre tous les nouveaux messages par
lots bornés et conserve pour reprise ceux qu'un LLM n'a pas classifiés. Les règles deviennent
un contrat fermé, les pannes partielles sont visibles et deux verrous empêchent les doubles
passages concurrents des workers et des actions manuelles.
La tranche v2.386 extrait le briefing quotidien dans `proactive_briefing.py`. Tâches,
événements et boîtes deviennent des sources injectées, concurrentes, bornées et observables.
Le service proactif et l'outil public partagent la même frontière; une indisponibilité
partielle n'est plus transformée silencieusement en liste vide.

## 4. Validation obligatoire par tranche

- revue et mise à jour de `SECURITY-DEBT-REGISTER.md` : aucune dette découverte ne peut être
  omise, minimisée ou fermée sans preuve; les entrées, sorties, persistances, privilèges,
  secrets, réseau, logs, dépendances, concurrence et rollback sont réévalués pour chaque
  composant modifié ;
- compilation Python ciblée ;
- test unitaire de la nouvelle frontière ;
- test de compatibilité de la façade historique ;
- test d'erreur et d'indisponibilité pertinent ;
- **gate de rollback obligatoire** : état antérieur identifié, procédure exacte documentée,
  données et schémas évalués, puis réversibilité vérifiée sans dépendre d'un fichier non
  versionné ; ce gate s'applique à chaque changement de code, frontend, configuration,
  script, dépendance, installation, documentation ou donnée ; une tranche irréversible est
  refusée ou redessinée avant intégration ;
- `scripts/check_architecture.py` ;
- `scripts/check_marvin.py --quick` ;
- redémarrage réel du backend ;
- `/api/health` avec version attendue, Ollama et workers ;
- `scripts/smoke_test_api.py` avec frontend Turbopack actif ;
- `git diff --check`, journal, version et commit atomique.

## 5. Critères de clôture backend

Le backend n'est déclaré consolidé que si :

- le Runner central est lisible et testé par phases ;
- `tools.py` et `database.py` sont des façades/assembleurs, pas des domaines monolithiques ;
- `main.py` est un composition root ;
- les contrats publics restent à 344 outils et 354 routes, sauf évolution fonctionnelle
  explicitement décidée ;
- aucune connexion SQLite directe ne contourne la fabrique ;
- les modes de confidentialité, Ultra cloud-only et Council cinq modèles restent couverts ;
- les reprises SSE, reçus idempotents et missions longues passent ;
- tous les tests rapides, le runtime réel et les smoke tests sont verts ;
- `AGENTS.md`, `ARCHITECTURE.md` et `DEVELOPMENT-JOURNAL.md` reflètent l'état réel ;
- l'arbre Git est propre et chaque tranche dispose d'un rollback vérifié, par réversion
  atomique du commit lorsqu'aucune donnée n'est migrée, ou par migration descendante/
  restauration contrôlée lorsqu'un état persistant évolue.

## 6. Hors périmètre jusqu'à clôture

Les améliorations frontend, avatar et UX restent planifiées, mais ne commencent pas avant la
clôture factuelle des phases A à D. Une correction frontend bloquante peut être faite plus tôt
uniquement si elle empêche de valider le backend par le smoke test.
Le gateway agentique HTTP rejoint `api/agent_gateway.py` en v2.402.0 : chat SSE, UI, catalogue
et MCP utilisent toujours les mêmes objets Runner/gateway, avec charges bornées et contrats
testables. `main.py` ne conserve plus ces modèles ni ces routes; restent le choix Cloud,
briefing/proactif et le handler global autour du composition root.
La sélection Cloud, le briefing et la configuration/exécution proactive rejoignent
`api/model_selection.py` et `api/proactive.py` en v2.403.0. Les besoins et branches sont
fermés, les charges sont typées et bornées, les erreurs de briefing sont corrélées sans
divulguer le message interne, et la forme top-level historique du briefing matinal reste
acceptée. Le service normalise aussi les anciennes configurations mal formées et journalise
les exceptions répétées du worker avec limitation temporelle. `main.py` ne contient plus que
le lifespan et le handler global comme fonctions actives. Son historique commenté redondant
est retiré au profit de Git et `DEVELOPMENT-JOURNAL.md`; le contrat
`scripts/test_main_composition.py` contrôle tous les routeurs, les imports, l'absence de cycle,
un import borné et le cycle de vie complet. **La phase D est terminée en v2.403.0.**
