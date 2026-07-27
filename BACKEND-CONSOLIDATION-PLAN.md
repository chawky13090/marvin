# Plan de consolidation complète du backend Marvin

Date de référence : 2026-07-26  
Version auditée : 2.300.0  
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
- 344 implémentations pour 344 spécifications et 346 routes sans doublon.

### Partiel

| Frontière | État mesuré | Reste |
|---|---:|---|
| Runner | Terminé en v2.313 : `agent.py` orchestre des frontières nommées | surveiller les régressions via les tests de contrat |
| Outils | `tools.py` : 20 197 lignes, 398 objets AST | extraire les domaines restants puis séparer catalogue et assemblage du registre |
| Persistance | `database.py` : 3 138 lignes, 143 objets AST | déplacer les domaines restants vers des repositories injectables |
| Composition FastAPI | `main.py` : 3 470 lignes, 44 routeurs, 12 fonctions/classes actives | extraire les derniers endpoints chat/MCP/proactif ; conserver seulement lifespan, assemblage et handlers globaux |
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

### Phase D — Composition et dépendances

1. extraire les derniers endpoints chat, outils/MCP et proactif ;
2. conserver `main.py` pour la création de l'application, le lifespan, le montage des routeurs
   et le handler global ;
3. supprimer les imports inversés entre API, outils et persistance ;
4. contrôler les cycles d'import et le temps d'import du backend.

## 4. Validation obligatoire par tranche

- compilation Python ciblée ;
- test unitaire de la nouvelle frontière ;
- test de compatibilité de la façade historique ;
- test d'erreur, rollback ou indisponibilité pertinent ;
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
- les contrats publics restent à 344 outils et 346 routes, sauf évolution fonctionnelle
  explicitement décidée ;
- aucune connexion SQLite directe ne contourne la fabrique ;
- les modes de confidentialité, Ultra cloud-only et Council cinq modèles restent couverts ;
- les reprises SSE, reçus idempotents et missions longues passent ;
- tous les tests rapides, le runtime réel et les smoke tests sont verts ;
- `AGENTS.md`, `ARCHITECTURE.md` et `DEVELOPMENT-JOURNAL.md` reflètent l'état réel ;
- l'arbre Git est propre et chaque tranche dispose d'un rollback par commit.

## 6. Hors périmètre jusqu'à clôture

Les améliorations frontend, avatar et UX restent planifiées, mais ne commencent pas avant la
clôture factuelle des phases A à D. Une correction frontend bloquante peut être faite plus tôt
uniquement si elle empêche de valider le backend par le smoke test.
