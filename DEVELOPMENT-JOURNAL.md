# Journal portable de développement de Marvin

Ce fichier est la mémoire de travail lisible par Codex, Claude ou un autre mainteneur. Toute
évolution importante doit y ajouter une entrée datée avec : demande, constats réels, décisions,
fichiers modifiés, validations et travaux restant éventuellement à faire. Ne jamais y copier de
mot de passe, jeton OAuth, clé privée ou contenu d'e-mail confidentiel.

## 2026-07-15 — Consolidation, e-mails multiboîtes et Council v2

### Fil de la conversation

1. L'utilisateur a demandé de prendre connaissance de Marvin, consolider le projet, recréer
   l'environnement, démarrer l'application et poursuivre jusqu'à stabilisation.
2. L'audit des conversations a montré des appels d'outils non demandés. Les versions 2.188 à
   2.190 ont introduit les contrôles d'architecture, les validations reproductibles et les
   garde-fous d'intention (« sans outil », réponses de quiz, rédaction directe).
3. L'utilisateur a demandé la gestion de plusieurs boîtes et plusieurs expéditeurs pour les
   réponses automatiques. Les versions 2.209 et 2.210 ont ajouté la saisie multi-valeurs,
   plusieurs comptes Gmail OAuth2 indépendants, les profils par boîte et l'orchestrateur
   idempotent avec simulation, file d'envoi et planification explicite.
4. L'utilisateur a précisé l'architecture attendue : Marvin utilise principalement Ollama Cloud ;
   les modèles locaux protègent les données sensibles dans les profils non débridés. Council doit
   faire juger les problèmes complexes par plusieurs modèles cloud différents.
5. L'audit du code et des journaux des 13–15 juillet a confirmé que « cherche en mode council »
   avait lancé des recherches web mais aucun appel `ai_model_council`. Council utilisait trois
   modèles choisis par ordre de configuration, pouvait viser un override retiré et pouvait
   attribuer à tort à un modèle cloud une réponse provenant du repli local.
6. L'utilisateur a demandé l'implémentation d'un vrai Council à cinq modèles et la correction des
   anomalies récentes, avec conservation permanente du contexte dans un fichier Markdown.

### Décisions de la version 2.211

- Council utilise exactement cinq réponses réussies provenant de cinq familles Ollama Cloud.
- Les cinq rôles sont : analyste, critique, vérificateur, alternatif et praticien.
- Après les réponses indépendantes, un membre effectue une critique anonymisée ; un autre arbitre
  les avis dans l'ordre inverse afin de réduire le biais de position.
- Un modèle cloud défaillant est remplacé par une autre famille cloud disponible. Aucun repli
  local n'est présenté sous le nom du modèle demandé.
- Le niveau de concurrence est configurable par `council_concurrency` et vaut 3 par défaut.
- Hors Ultra débridé, une question sensible reste interdite au Council Cloud. En Ultra, le choix
  explicite de l'utilisateur est respecté.
- « mode Council » et les formulations équivalentes constituent une intention obligatoire : le
  moteur ne peut plus conclure avant d'avoir réellement exécuté `ai_model_council`.
- Un override cloud absent de `/api/tags` est remplacé par un modèle installé plutôt que tenté
  aveuglément. Les modèles portant `code` ou `coder` sont reconnus comme spécialistes du code.
- Le routage sensible analyse aussi le contenu récent, afin que « résume ça » après un contenu
  sensible reste local dans les modes protégés.
- Le niveau Expert conserve toutes les fonctionnalités, mais ne préconfirme plus les envois,
  suppressions et actions distantes. Elles demandent toujours un accord humain explicite.
- Les appels `pc_run_powershell` utilisant `command` sont normalisés vers `script`.
- `ssh_connection_save` enregistre nom/hôte/port/utilisateur sans accepter de secret ; les mots de
  passe et clés restent saisis directement par l'utilisateur dans l'écran SSH.

### Fichiers touchés par cette étape

- `backend/tools.py` : Council v2, provenance cloud, outil SSH sans secret.
- `backend/cloud_routing.py` : familles, sélection distincte, validation des overrides, code.
- `backend/agent.py` : déclenchement obligatoire, historique sensible, confirmations Expert,
  normalisation des anciens appels.
- `backend/intent_guard.py` : détection pure de l'intention Council.
- `scripts/test_intent_guards.py`, `scripts/test_council.py`, `scripts/check_marvin.py` : régressions.
- `backend/app_version.py`, `package.json`, `package-lock.json`, `README.md`, `ARCHITECTURE.md`,
  `AGENTS.md`, `backend/main.py` : version et documentation portable.

### Vérifications exécutées

- `check_marvin.py --quick` : 8 étapes réussies, compilation de 60 fichiers, dépendances
  cohérentes, lint sans erreur (37 avertissements préexistants).
- Architecture : Marvin 2.211.0, 335 outils synchronisés, 271 routes, 34 pages.
- Test Council réel : succès en 299,2 s avec cinq familles finales — DeepSeek V4 Pro,
  Qwen 3.5, GLM 5.2, MiniMax M3 et Mistral Large 3. Nemotron a échoué comme membre initial et
  a été remplacé par une autre famille cloud ; critique réussie, arbitrage par DeepSeek,
  réponse finale de 5 495 caractères.
- Le journal de tentatives du panel conserve désormais aussi les membres remplacés et leur erreur.

### Clôture technique

- Build de production Next.js réussi.
- L'ancien backend 2.210 lancé en administrateur a dû être arrêté explicitement ; le backend
  2.211 est maintenant lancé de façon détachée et reste actif.
- `/api/health` confirme `version=2.211.0`, `tools_count=335` et `tools_spec_count=335`.
- Override cloud actif : `deepseek-v4-pro:cloud` pour chat, agent et analyse ; le routage par
  tâche peut toujours choisir un spécialiste installé.
- Smoke API : 23/23 contrats réussis.
- Smoke pages : 34/34 pages réussies.
- Smoke chat : 5/5 conversations représentatives réussies, dont l'envoi e-mail et les études
  longues observées dans les conversations récentes.

Entrée terminée sans fonctionnalité retirée. Un outil a été ajouté (`ssh_connection_save`).

## 2026-07-16 — Proposition de modes dans la barre de chat

Demande : rendre Council et les modes réellement utiles accessibles depuis la barre de chat.

Proposition retenue pour une future implémentation : ajouter une pastille séparée `✨ Auto` près
du bouton d'envoi. Le menu `+` reste réservé aux images, documents et compétences. Le mode choisi
s'applique par défaut au prochain message seulement, puis revient sur Auto ; une épingle permet de
le conserver pendant toute la conversation.

Modes proposés :

- `✨ Auto` : routage actuel et choix automatique des outils ; valeur par défaut.
- `💬 Direct` : réponse dans le chat, sans outil.
- `🌐 Recherche` : informations actuelles avec recherche web et sources.
- `🔬 Approfondie` : recherche multi-passes, plus lente.
- `🏛️ Council 5` : cinq familles Ollama Cloud, critique et arbitrage.
- `🔒 Local privé` : force un modèle local pour ce message, même si le profil global autorise le cloud.

Council peut proposer une option `Rechercher d'abord` afin de fournir aux cinq membres un dossier
de preuves commun via le champ `evidence`. L'interface doit afficher avant envoi une estimation de
durée/coût (`lent`, `5 modèles cloud`) et désactiver Council en Hyper local avec une explication.
Le mode doit être transmis au backend dans un champ structuré, jamais simulé en préfixant le texte
de l'utilisateur. Chaque message affichera ensuite le badge du mode réellement exécuté.

État : proposition uniquement, aucune modification fonctionnelle réalisée à cette étape.

## 2026-07-16 — Refonte de la proposition : Marvin Cortex et contrat de mission

L'utilisateur demande de dépasser les modèles frontier et leurs interfaces, pas de les copier.
Après comparaison des produits officiels OpenAI, Anthropic, Google Gemini et Perplexity, la
proposition précédente de six modes plats est abandonnée comme architecture cible. Ces produits
proposent déjà des sélecteurs Research/Agent/Canvas, des plans modifiables, des sources connectées,
une progression interruptible, des citations et des exports. Ajouter seulement une entrée Council
dans une liste n'apporterait pas un avantage durable.

### Décision produit

La barre de chat doit exposer un unique contrôleur adaptatif, `Cortex`, qui compile chaque demande
en un **contrat de mission structuré**, visible et modifiable avant l'envoi. L'utilisateur exprime
le résultat attendu ; Marvin choisit les modèles et outils. Le contrat comporte six axes :

1. effort : instantané, standard, approfondi ou mission autonome ;
2. preuves : aucune, mémoire locale, web, sources primaires ou sources connectées ;
3. révision : réponse simple, vérification, Council si désaccord ou Council 5 forcé ;
4. autonomie : conseiller, préparer, exécuter avec confirmations ou mission suivie ;
5. confidentialité : auto, local strict, hybride expurgé ou cloud autorisé ;
6. livrable : chat, synthèse, rapport, document, tableau ou workflow réutilisable.

Dans l'état compact, une seule pastille près de l'envoi résume le routage réel, par exemple :
`Cortex · sources primaires · Council si désaccord · hybride privé · rapport`. Un clic ouvre les
six axes. Les choix sont par message, épinglables pour la conversation et enregistrables comme
recette de mission. Le sélecteur technique de modèle reste disponible dans les paramètres avancés,
mais ne doit plus être la décision principale demandée à l'utilisateur.

### Orchestration différenciante

- **Escalade adaptative** : réponse rapide d'abord ; recherche si la fraîcheur ou les preuves le
  nécessitent ; vérificateur ensuite ; Council 5 seulement si le risque, l'incertitude ou le
  désaccord dépassent un seuil. Une demande explicite de Council reste impérative.
- **Passerelle privée hybride** : les données sensibles sont extraites et pseudonymisées localement,
  les modèles cloud ne reçoivent qu'un dossier expurgé, puis Marvin réhydrate localement la réponse.
  Local strict et Ultra débridé restent disponibles sans modifier leurs garanties actuelles.
- **Graphe d'exécution vivant** : plan, recherches, outils, modèles, validations et livrable sont des
  nœuds visibles, interruptibles et rejouables. L'utilisateur peut bifurquer depuis un nœud ou le
  relancer avec une autre politique sans recommencer toute la conversation.
- **Registre de preuves par affirmation** : chaque affirmation importante peut être reliée à sa
  source, son outil, son modèle, sa date et son niveau de confiance. L'interface distingue clairement
  fait vérifié, inférence et point non résolu.
- **Autorisation par portée** : avant une action, Marvin affiche ce qui sera lu, transmis ou modifié,
  le caractère réversible et le point de confirmation. L'utilisateur peut approuver une étape, la
  mission réversible ou une règle temporaire, au lieu de confirmer aveuglément chaque outil.
- **Recettes auto-améliorées** : une mission réussie peut devenir une recette combinant contrat,
  compétence, sources, format de sortie et déroulé gagnant. Les traces de succès et le système de
  compétences existants servent à améliorer la recette sans rendre les compétences exécutables.

### Interface cible

Le chat reste minimal. Pendant une mission, un atelier latéral facultatif affiche le graphe en cours,
les preuves, les artefacts et les variantes du Council. Après réponse, une barre de confiance compacte
montre : route de confidentialité, outils réellement utilisés, modèles consultés, couverture des
preuves, divergences et éléments restant incertains. Les détails restent repliés par défaut.

### Compatibilité avec le socle actuel

Le projet possède déjà les briques nécessaires : routage local/cloud, modes de confidentialité,
permissions, Council 5, recherche profonde, tâches longues, workflows, audit, compétences et traces
de succès. Le manque principal est une enveloppe de requête structurée (`ChatRequest` ne transporte
actuellement que messages, conversation, modèle), un planificateur de contrat et les événements SSE
de graphe/provenance. L'implémentation devra être incrémentale et préserver les 335 outils ainsi que
les comportements existants en utilisant `Cortex Auto` comme valeur rétrocompatible.

Ordre recommandé : (1) schéma de contrat + routage déterministe + tests, (2) pastille Cortex et aperçu
avant envoi, (3) escalade vérification/Council, (4) registre de preuves, (5) atelier et graphe rejouable,
(6) passerelle hybride expurgée, (7) recettes de mission et mesures de qualité. Chaque phase doit être
validée sur de vraies conversations et comparée à une référence simple avant activation générale.

Sources de référence consultées : documentation officielle OpenAI Deep Research/Agent/Projects,
Anthropic Research/Integrations, Google Gemini Deep Research/Canvas et Perplexity Research.

État : proposition d'architecture seulement ; aucune fonctionnalité n'a été retirée ou modifiée.

## 2026-07-16 — Implémentation Marvin Cortex v2.212

L'utilisateur a validé la mise en place complète. Cortex est désormais intégré sans supprimer les
335 outils ni modifier le texte des messages utilisateur.

Livré :

- contrat structuré à six axes (`effort`, `evidence`, `review`, `autonomy`, `privacy`, `output`) ;
- compilation déterministe et explicable dans `backend/cortex.py` ; les choix `Auto` n'imposent
  aucun outil et une valeur cliente inconnue est ignorée ;
- champ `cortex` ajouté à `/api/chat` et transmis à `run_agent` séparément du message ;
- pastille `Cortex` dans la barre de chat, éditeur compact des six axes, choix par message,
  épinglage de conversation et réinitialisation ;
- recherche web/profonde, Council 5, tâche longue et document réellement imposables par un choix
  explicite ; le mapping d'arguments est déterministe et ne dépend pas d'un préfixe ajouté au texte ;
- autonomie `Conseiller` coupe les outils quand aucune preuve explicite n'est demandée ;
- confidentialité `Local strict` prioritaire par message ; le mode hybride rebascule localement dès
  qu'une donnée sensible est détectée, y compris face à une sélection manuelle cloud ;
- révision indépendante applicable aux réponses sans code lorsque demandée ; `Council si désaccord`
  n'appelle les cinq modèles que si le vérificateur indépendant remonte réellement un problème ;
- événements SSE `cortex_contract` et `cortex_provenance`, graphe d'exécution dérivé des vrais
  `tool_start/tool_end`, route modèle/confidentialité et couverture des citations visibles sous la réponse ;
- recettes persistantes dans `data/cortex_recipes.json`, API de liste/création/suppression et mesure
  du taux de succès avec conservation de la plus courte trace d'outils réussie ;
- test déterministe `scripts/test_cortex.py`, ajouté à `npm run check:quick` et commande dédiée
  `npm run check:cortex` ; version publique synchronisée en `2.212.0`.

Garde-fous conservés : les contrats ne contiennent aucun code exécutable, ne contournent ni les
permissions ni les confirmations, le verrou Hyper local reste prioritaire et une escalade Council
sensible reste refusée hors Ultra par le Council existant.

Validation finale réelle :

- `npm run build` réussi ;
- `npm run check:quick` réussi ;
- `npm run check:live` réussi en 12/12 étapes : runtime natif, architecture, intentions, Council,
  Cortex, e-mail, dépendances Python, compilation, lint, HTTP, pages et chat ;
- 335 outils et 274 routes préservés, aucun outil supprimé ;
- 23/23 contrats HTTP et 34/34 pages validés sur les services réellement lancés ;
- recette Cortex créée, relue puis supprimée par l'API ;
- échange SSE réel en mode `Conseiller + Local strict` : contrat compilé et provenance reçus, aucun
  `tool_start`, donc aucun outil déclenché sans demande ;
- test visuel dans Marvin : ouverture de la pastille, six axes présents et combinaison
  `Council si désaccord + Local strict + Rapport` correctement reflétée dans la barre ;
- défaut d'empilement découvert pendant ce test : le fond du panneau interceptait le premier clic
  sur `Réinitialiser`. Le bouton passe maintenant au-dessus du fond quand le panneau est ouvert ;
  réinitialisation en un clic validée et état final remis sur `Auto adaptatif` ;
- console frontend sans erreur ; ESLint reste à 0 erreur et 37 avertissements historiques hors Cortex.

Incident de redémarrage découvert et corrigé : sous une console Windows `cp1252`, certains `print`
avec emoji pouvaient faire échouer le backend avant l'ouverture du port 8005. `main.py` reconfigure
maintenant `stdout` et `stderr` avec `errors="replace"`, ce qui rend le démarrage robuste sans retirer
les messages de diagnostic. Backend et frontend ont été relancés et exposent Marvin `2.212.0`.

## 2026-07-16 — Marvin Forge v2.213 et conflit de port Ollama

Après installation de Docker, `start.bat` échouait avec `WSAEACCES` sur
`127.0.0.1:11434`. Le diagnostic `netsh interface ipv4 show excludedportrange protocol=tcp`
a établi que Hyper-V/Docker excluait la plage `11342-11441`. Aucun processus n'occupait
le port. La suppression des exclusions a été écartée car elle serait intrusive, dépendante
des privilèges administrateur et non durable après redémarrage.

Décision : `scripts/resolve-ollama-port.ps1` sélectionne d'abord 11434, puis une liste
bornée de ports locaux, en vérifiant les exclusions, l'API existante et un bind réel.
`start.bat` propage le choix dans `OLLAMA_HOST`, `OLLAMA_URL`, `OLLAMA_BASE_URL` et
`NEXT_PUBLIC_OLLAMA_PORT`. L'exécutable est résolu par
`scripts/resolve-ollama-exe.ps1`, sans dépendre d'un `LOCALAPPDATA` ou d'un `PATH`
incohérent. Sur cette machine, le port retenu est 12434. Ollama, FastAPI et Next.js
ont ensuite répondu respectivement sur 12434, 8005 et 3000.

Le plan Marvin Forge accepté par l'utilisateur est engagé dans la même version :

- `backend/forge.py` : corpus JSON, traces JSONL append-only, graders déterministes,
  outils requis/interdits, durée, contenu et métriques de répétabilité ;
- `backend/api/forge.py` : scénarios, notation, runs et synthèse ;
- `scripts/run_forge.py` : exécution HTTP contre le backend actif, sans second accès Qdrant ;
- `scripts/test_forge.py` : régressions sans réseau ni LLM ;
- `app/forge/page.jsx` : tableau de bord en lecture seule ;
- scénario actif initial : réponse `OK` sans outil ; Council et recherche désactivés par
  défaut pour éviter un coût ou un effet de bord involontaire.

## 2026-07-16 — Cortex Search v2.214

La phase 2 de la feuille de route est engagée après validation Forge `pass^3=true`.
`backend/cortex_search.py` explore trois stratégies indépendantes (systémique,
conservatrice et alternative), puis utilise cinq vérificateurs distincts : exactitude,
preuves, contraintes, risques et exécution. Un arbitre synthétise la décision sans
transformer artificiellement les désaccords en consensus.

Le déclenchement est explicite via l'axe Révision de Cortex (`search`) et force l'outil
`ai_cortex_search`. Les règles de confidentialité du Council sont conservées : Cloud requis,
Hyper local bloquant, données sensibles bloquées hors Ultra débridé. Le registre compte
désormais 336 outils. Les régressions déterministes vérifient le contrat, le registre,
les cinq vérificateurs et les blocages de confidentialité sans consommer de quota cloud.

Anomalie découverte pendant le redémarrage réel : FastAPI pouvait quitter au démarrage sous une
console Windows cp1252, car les messages d'auto-configuration contiennent des emoji et `print`
levait `UnicodeEncodeError`. `main.py` reconfigure maintenant stdout/stderr en mode de remplacement
tolérant ; le contenu fonctionnel et les diagnostics restent présents et le démarrage ne dépend plus
du terminal utilisé.
## 2026-07-16 — Mission OS et Proof-Carrying Actions v2.215

La phase 3 réutilise volontairement le moteur `long_task_start` et les tâches/Cron
existants au lieu de créer un ordonnanceur concurrent. Après confirmation du plan,
une mission durable est créée avec son objectif, sa conversation, son tag, ses étapes,
ses identifiants de tâches, ses critères de réussite et ses checkpoints.

Chaque outil exécuté depuis le chat produit désormais un événement `action_proof` dans
`data/mission_events.jsonl`. Les arguments sont expurgés des mots de passe, tokens, clés,
cookies et secrets. La preuve contient la durée, le résultat compact, l'état
`succeeded/failed/confirmation_required`, un indicateur de vérification et une stratégie
de rollback quand elle est définissable. Les missions vivent dans `data/missions.json`,
sont synchronisées avec l'état des tâches longues et sont consultables via
`/api/missions`. Tests isolés avec stockage temporaire dans `scripts/test_mission_os.py`.
## 2026-07-16 — Memory Mesh et Truth Ledger v2.216

La phase 4 évite une migration risquée de SQLite/Qdrant. `memory_mesh.py` conserve dans
un sidecar les types working, episodic, semantic et procedural, ainsi que source,
confiance, sensibilité, expiration et compte d'utilisation. `memory_save` alimente ce
sidecar après création, mise à jour ou dédoublonnage.

`truth_ledger.py` découpe les réponses finales en affirmations et les relie aux URL,
outils de preuve, revue et confiance disponibles dans la provenance Cortex. Le registre
est append-only dans `data/truth_ledger.jsonl` et consultable via `/api/knowledge`.
Cette première version ne prétend pas prouver formellement chaque phrase : elle distingue
explicitement `sourced`, `tool_supported` et `unsupported`.

## 2026-07-16 — Model Market et Research Swarm v2.217

La phase 5 réutilise l'inventaire dynamique Ollama Cloud et l'apprentissage passif
de `cloud_routing.py`. Aucun benchmark payant n'est lancé automatiquement. Model Market
classe les modèles réellement installés par besoin (`general`, `code`, `vision`,
`research`, `verification`, `synthesis`) à partir de la famille, des capacités déjà
prouvées, du taux de succès et de la latence observée pendant les appels utiles.
La télémétrie technique append-only ne conserve aucun prompt ni contenu utilisateur.

Research Swarm orchestre jusqu'à cinq familles distinctes avec les rôles sources
primaires, état de l'art, contradicteur, praticien et vérificateur. Chaque cellule collecte
ses sources web, analyse uniquement les éléments trouvés, puis une vérification croisée
et une synthèse finale préservent les contradictions et incertitudes. Les modes Hyper
local et sensible hors Ultra débridé bloquent le pipeline. La phase est exposée par
`ai_research_swarm`, l'axe Cortex `swarm`, `/api/model-market/*` et la page `/market`.

Validations déterministes observées : compilation Python réussie, contrat Cortex vert,
registre et schéma synchronisés à 337 outils, 291 routes et 36 pages. Le test
`scripts/test_model_market.py` n'effectue aucun appel réseau ou cloud.

Validation réelle bornée : un essaim de trois cellules et une source maximum par cellule
a terminé en 88,6 secondes, avec trois familles cloud, synthèse de 5 866 caractères et
persistance du run `swarm-3420eb0895d1`. Ce test a révélé une ambiguïté des citations locales,
corrigée avant clôture par des références uniques de type `[cell-N]`.

## 2026-07-16 — Research Swarm 5.1, Evolution Lab et Mission Canvas v2.220

Research Swarm peut désormais être lancé comme job durable : état persistant, progression,
annulation, détection des exécutions interrompues par un redémarrage, reprise explicite,
budget de durée et métriques de sources uniques, domaines et doublons. Le endpoint bloquant
historique reste compatible, tandis que l'interface `/market` utilise les jobs.

Evolution Lab n'autorise pas l'auto-modification libre du code. Les premières expériences
portent sur une liste blanche de paramètres bornés. Une promotion exige au moins trois essais
baseline et candidate, un taux de succès strictement meilleur, aucune panne critique, une
latence inférieure à 125 % de la baseline et une confirmation explicite. La valeur précédente
est conservée pour rollback.

Mission Canvas `/missions` projette l'état Mission OS, les étapes et la chronologie des
preuves. Pause, reprise et retry d'une étape sont des transitions persistantes ; le retry
réinitialise uniquement la tâche concernée et ne rejoue pas les étapes déjà terminées.

## 2026-07-16 — Parcours phase 6 complets v2.221

La première interface de la phase 6 exposait les données mais ne permettait pas encore
de réaliser tous les parcours. `/market` lit maintenant le flux SSE du job au lieu de
sonder périodiquement l'API. `/evolution` accepte les essais baseline/candidate en JSON,
calcule les seuils puis expose promotion et rollback. `/missions` rafraîchit le détail
sélectionné, permet les checkpoints et demande une confirmation locale avant pause ou retry.
Le lint reste à zéro erreur et aucun nouvel avertissement React n'a été introduit.

## 2026-07-16 — Frontier Arena et Evidence Fabric v2.222

La phase 7 commence par un socle mesurable. Frontier Arena réutilise les scénarios Forge
pour importer une réponse Marvin ou externe, puis calcule sans juge LLM la réussite du
livrable, la couverture des preuves, la dette épistémique, la durée, le coût, les
interventions humaines et les violations de confidentialité. Le tableau de bord `/forge`
expose le classement et un formulaire d'import.

Evidence Fabric remplace le rapprochement limité aux URL littérales. Les affirmations
comprennent maintenant les références `[cell-N]`, les domaines indépendants, le niveau
d'autorité probable, l'empreinte SHA-256 du contenu observé et les contradictions. Le
Source Firewall marque systématiquement les sources externes comme données non fiables et
signale les formulations ressemblant à une injection ; il ne transforme jamais leur
contenu en instruction ou en action.

Research Swarm encapsule explicitement les pages dans des blocs de données non fiables et
joint à chaque exécution un bundle de preuves par affirmation. Le Truth Ledger conserve la
dette épistémique et l'état du Source Firewall. Validations déterministes ajoutées dans
`scripts/test_frontier_arena.py` et étendues dans `scripts/test_knowledge_mesh.py`.

Validation réelle : `scripts/check_marvin.py --quick` termine 16/16 étapes, avec 337 outils,
309 routes, 38 pages, aucune dépendance Python cassée, compilation de 78 fichiers Python et
zéro erreur ESLint ; les 37 avertissements sont antérieurs. Après redémarrage, `/api/health`
annonce bien `2.222.0`, les 25 contrats HTTP passent et `/forge` répond HTTP 200 avec
`Marvin Forge` et `Frontier Arena` dans le rendu. Le smoke test Playwright global a été
bloqué avant navigation sur les 38 pages par `ERR_NETWORK_ACCESS_DENIED` côté navigateur de
test Windows ; ce résultat environnemental est distinct des contrats HTTP réussis.

## 2026-07-16 — Evidence Fabric 2 et Arena aveugle v2.223

Evidence Fabric distingue désormais la présence d'une citation, la disponibilité d'un
extrait, le soutien lexical et la corroboration par plusieurs domaines indépendants. Les
dates de publication sont normalisées en état `current`, `stale`, `unknown` ou `invalid` ;
une source obsolète augmente la dette et réduit la confiance au lieu d'être traitée comme
une preuve équivalente à une documentation actuelle.

Frontier Arena crée des duels limités à deux systèmes différents sur le même scénario.
L'ordre A/B est aléatoire et l'API masque fournisseur, identifiant de soumission, scores
automatiques, durée, coût et dette avant le vote. Le réviseur note séparément exactitude,
complétude, preuves et utilité de 1 à 5, puis choisit A, B ou égalité. Les identités sont
révélées uniquement après enregistrement. Le score humain ne contribue au classement
composite qu'après trois duels, afin qu'un vote isolé ne modifie pas le classement.

Validation réelle : 16/16 étapes rapides, 337 outils, 313 routes, 38 pages, compilation de
78 fichiers Python, zéro erreur ESLint et 37 avertissements antérieurs. Après redémarrage,
`/api/health` annonce `2.223.0`, `/forge` contient le parcours « Duel en aveugle » et les
25 contrats HTTP, y compris les statistiques de duels, passent.

## 2026-07-16 — Vérification sémantique et Adaptive Team Runtime v2.224

La clôture d'Evidence Fabric ajoute deux juges sémantiques contradictoires de familles
Ollama Cloud distinctes. Le premier refuse les citations décoratives malgré une posture
orientée soutien ; le second cherche en priorité contradictions et généralisations abusives.
Leurs sorties JSON sont filtrées, bornées et fusionnées par code. Un désaccord
support/contradiction devient `disputed` au lieu d'être arbitré silencieusement.

Adaptive Team améliore directement le raisonnement visible dans le chat. Le moteur détecte
recherche actuelle, architecture technique, décision, risque, profondeur et contraintes,
puis choisit un pipeline borné à deux étapes. Pour une étude technique actuelle, Research
Swarm collecte et vérifie d'abord les sources, puis Cortex Search reçoit ce dossier comme
preuve et explore plusieurs solutions avec cinq vérificateurs. Une décision sans recherche
peut utiliser Council. Le chat expose le plan et les résultats intermédiaires.

L'activation automatique reste volontairement restrictive : message d'au moins 60
caractères, demande explicite de profondeur ou de plusieurs experts, complexité suffisante,
route cloud autorisée et contenu non sensible. Les demandes simples, rédactions directes,
interdictions d'outil et profils protégés ne déclenchent pas l'équipe.

Validation réelle : Adaptive Team a choisi uniquement Cortex Search pour une demande de
conception sans besoin web, mobilisé cinq familles (`deepseek`, `glm`, `mistral`,
`nemotron`, `qwen`), terminé en 195,6 secondes et produit 7 966 caractères. Un Research
Swarm réduit à trois cellules et une source par cellule a terminé en 192,4 secondes ; ses
deux juges sémantiques ont tous deux répondu, avec 16 affirmations soutenues, 75
insuffisantes, aucune contradiction et une dette de 0,5709. Ce résultat a conduit à
interdire le libellé générique « résultat vérifié » entre étapes : Adaptive Team transmet
désormais la dette et les comptes de verdicts à Cortex, avec instruction de ne pas reprendre
comme faits les affirmations insuffisantes, disputées ou contredites.

## 2026-07-16 — Code Forge et qualité expert des scripts v2.225

Le retour utilisateur indique une note externe de 2/10 sur des scripts Marvin. La
conversation « Script Zabbix sécurisé HTTPS » confirme un défaut systémique : URL de dépôt
construite avec le codename au lieu du numéro Debian, fallback Trixie vers Bookworm non
supporté, variables `ADMIN_PASS` et `TOTP_SECRET` non définies sous `set -u`, secrets
affichés et stockés, sauvegarde installée dans `/etc/cron.daily` mais appelée depuis
`/usr/sbin`, Fail2ban relié au journal serveur au lieu des authentifications web, ports
ouverts globalement, commandes non idempotentes et affirmations finales contradictoires sur
la version LTS. Le Council avait amélioré la longueur et l'apparence, pas l'exécutabilité.

Code Forge remplace cette logique pour les livrables de code : architecte, implémentation
complète, reviewer production, reviewer sécurité, réparation, validation syntaxique locale
et gatekeeper final. Le résultat n'est accepté que si la syntaxe et les contrôles
structurels passent, que le gatekeeper fournit un JSON valide, attribue au moins 8/10 et ne
signale aucun problème critique ou élevé. Les validateurs utilisent `ast.parse` pour Python,
le parser `System.Management.Automation` pour PowerShell, `node --check` pour JavaScript,
`bash -n` lorsqu'un Bash local est disponible et `json.loads` pour JSON. Aucun code généré
n'est exécuté pendant la validation.

Premier essai réel sur le cas Zabbix : le pipeline a correctement choisi
`research_swarm -> code_forge`, complexité 9, mais le modèle d'implémentation
`kimi-k2.7-code:cloud` a dépassé le timeout de 240 secondes. Adaptive Team a alors déclaré
à tort un succès global grâce à la seule recherche. Correction immédiate : la dernière
étape d'un pipeline de livrable est désormais obligatoire ; son échec rend le pipeline en
échec et aucun rapport préparatoire n'est substitué au script. Code Forge utilise maintenant
le modèle code le mieux classé pour l'implémentation, un timeout borné à 360 secondes et
jusqu'à deux modèles cloud de repli supplémentaires. L'échec et son type continuent
d'alimenter Model Market afin de déclasser automatiquement un modèle trop lent.

Deuxième essai réel direct : Code Forge a produit 27 779 caractères, déclenché sa
réparation et refusé le résultat. Le gatekeeper indépendant a relevé deux défauts critiques
réels : mot de passe MariaDB exposé dans les arguments des processus et paquet Debian 12
utilisé sur Debian 13. Il a aussi relevé un rollback incomplet. Le score final est resté à
0/10 ; Marvin n'a donc pas présenté ce script comme une livraison experte. Deux faux
positifs du validateur ont été corrigés séparément : les variables d'environnement utilisées
avec `${VAR:-}` sont optionnelles et l'aide affichant le nom `ZBX_DB_PASSWORD` n'affiche pas
la valeur du secret.

Troisième essai réel via Adaptive Team : Research Swarm a réussi, puis Code Forge a de
nouveau refusé le livrable au lieu de recycler la synthèse de recherche. L'analyse a montré
que les requêtes de recherche restaient trop longues et que les extraits officiels n'étaient
pas transmis intégralement au générateur. Research Swarm construit maintenant des requêtes
courtes par rôle, privilégie les domaines correspondant au produit et les documentations,
puis transmet une enveloppe de preuves contenant synthèse, URL et extraits observés.

La boucle de qualité a été renforcée conformément aux résultats publiés sur les agents de
code : deux itérations maximales evaluator-optimizer, modèle de réparation différent à la
seconde tentative, relecture après chaque correction, conservation d'un seuil 8/10 sans
problème critique ou élevé, contexte de code porté à 50 000 caractères et sorties des
reviewers bornées à 4 000 tokens avec température nulle. Les diagnostics du gate sont
désormais conservés dans Adaptive Team : validité de la revue, contrôles échoués, verdict,
constats, nombre de réparations et longueur du code. Les sources consultées pour cette
décision sont la documentation officielle Ollama sur `/api/generate`, SWE-bench, SWT-Bench
et le motif evaluator-optimizer publié par Anthropic.

Validation réelle après ces corrections : `scripts/test_code_forge.py`,
`scripts/test_model_market.py` et `scripts/test_adaptive_team.py` passent ; la validation
rapide complète passe 18/18 étapes, avec 339 outils, 313 routes, 38 pages, 81 fichiers
Python compilés, zéro erreur ESLint et 37 avertissements préexistants. La validation ne
baisse pas le seuil pour obtenir artificiellement un succès : un script insuffisant reste
explicitement refusé.

Le backend actif était resté sur une ancienne instance lancée avec des droits supérieurs :
les redémarrages non élevés lançaient un nouveau processus qui quittait après conflit de
port, tandis que le health check répondait depuis l'ancien processus. Le diagnostic a aussi
montré que le shim `backend/.venv/Scripts/python.exe` crée un processus Python enfant qui
porte réellement le port 8005. Le redémarrage fiable vérifie maintenant la filiation entre
le lanceur et le listener au lieu d'exiger une égalité de PID.

Après rechargement réel, Code Forge a bien exécuté deux réparations et fait passer tous les
contrôles déterministes. Les trois appels au gatekeeper DeepSeek ont toutefois renvoyé une
réponse vide. Un repli borné vers quatre modèles de revue distincts a été ajouté ; chaque
tentative, erreur et durée est conservée. Le test suivant a obtenu une revue valide via
Mistral puis Qwen. Les deux juges ont encore refusé le script pour des défauts réels :
variable FQDN non restaurée en rollback, secret dans `mysql -p`, interpolation SQL,
détection de schéma incorrecte et conflit entre vhost Apache manuel et Certbot. Une
affirmation du juge sur l'inexistence de Zabbix 7.4 contredisait la source officielle ;
les preuves sont donc maintenant incluses explicitement dans chaque prompt de gate et de
réparation.

Le score brut d'un juge ne peut plus masquer ses propres constats : toute issue critique
borne le score normalisé à 4/10 et toute issue élevée à 7/10. Un nouveau contrôle statique
détecte les secrets placés dans les arguments de `mysql`, `mariadb`, `psql`, `sed`, `sh`
ou `bash`. La boucle accepte désormais jusqu'à trois réparations, chacune suivie d'une
nouvelle revue. Le résultat observé reste volontairement refusé tant que les problèmes
critiques ne sont pas éliminés ; cette non-livraison est un comportement correct du gate,
mais la génération doit encore être améliorée avant de considérer le cas Zabbix comme
réussi.

## 2026-07-16 — Test Forge, conteneurs jetables et preuve d'exécution v2.226

La demande utilisateur impose que Marvin sache coder et scripter au niveau production, et
valide explicitement l'utilisation de conteneurs jetables avec Internet pour tester les
installations. La conception retient deux niveaux afin de ne pas donner immédiatement un
accès réseau à du code encore non fiable.

Le premier niveau est hors ligne et obligatoire. Chaque conteneur utilise une image
épinglée, `--network none`, une racine en lecture seule, `--cap-drop ALL`,
`no-new-privileges`, un montage hôte strictement en lecture seule, aucune exposition de
port, aucun socket Docker et des limites CPU, mémoire et processus. Bash utilise
ShellCheck 0.11.0, `bash -n` et Bats 1.13.0. Python utilise l'image officielle 3.12.13,
une compilation en mémoire sans création de `__pycache__`, puis `unittest`. JavaScript
utilise Node.js 22.23.1 avec `node --check` et `node:test`. Une suite de tests réelle est
obligatoire ; lint ou syntaxe seuls ne donnent jamais `production_ready=true`.

Le second niveau concerne les installeurs Bash. Après réussite hors ligne, un Debian 13
daté (`trixie-20260713-slim`) est démarré avec Internet, racine jetable modifiable, aucun
secret hôte, aucun port publié, aucun socket Docker, sans mode privilégié et avec ressources
bornées. Le code doit exposer `--integration-test`. Un harness séparé copie le script dans
le stockage temporaire, exécute réellement dépôts, téléchargements, paquets et contrôles,
puis ne peut annoncer `MARVIN_INTEGRATION_COMPLETE=full` qu'après réussite complète.
L'image n'est jamais téléchargée implicitement pendant une validation (`--pull never`) :
la préparation des images est une étape explicite et contrôlée.

Test réel observé : un script Bash minimal a effectué `apt-get update`, installé `jq`
depuis Internet sous Debian 13, vérifié `jq-1.7`, puis produit le marqueur final. Avant ce
passage en ligne, le même livrable avait réussi `bash -n`, ShellCheck sans constat et un
test Bats. Le conteneur a été supprimé automatiquement et aucun port n'a été publié.

Code Forge génère maintenant les tests unitaires et, pour les installeurs, le harness
d'intégration. Les échecs Test Forge déclenchent jusqu'à deux corrections supplémentaires
du code, suivies d'une régénération des tests et d'une nouvelle exécution. Le gatekeeper
final reçoit les preuves d'exécution et le statut production exige simultanément validation
structurelle, Test Forge réussi, revue JSON valide, score d'au moins 8/10 et absence de
problème critique ou élevé.

L'outil explicite `ai_test_forge` permet aussi de valider un livrable fourni. La page de
chat affiche désormais chaque étape de test et son code de sortie. Le script
`scripts/prepare-test-forge.ps1` installe les cinq images épinglées et les modules
PowerShell. `INSTALLER-NOUVEAU-PC.bat` prépare Test Forge lorsque Docker répond ;
`VERIFIER-INSTALLATION.bat` considère Docker indisponible comme un défaut de capacité
production.

PSScriptAnalyzer 1.25.0 et Pester 5.8.0 ont été installés dans le profil utilisateur.
PowerShell passe actuellement le parser et l'analyse statique, mais n'est pas exécuté :
Windows Sandbox n'est pas installé et une exécution Pester locale ne constitue pas une
isolation suffisante. Le statut production PowerShell reste donc volontairement refusé
jusqu'à la mise en place d'une VM Windows jetable Hyper-V.

Références techniques consultées : documentation Docker pour `--network none`,
`--read-only`, ressources et `no-new-privileges` ; documentation officielle ShellCheck,
Bats, pytest, PSScriptAnalyzer et PowerShell Gallery ; images officielles Docker Python,
Node et Debian.

Premier essai Code Forge complet après activation de Test Forge : un utilitaire Python de
déduplication CSV compile, mais cinq tests sur vingt-quatre échouent. Deux corrections
automatiques n'ont pas suffi et le gate final a encore signalé des problèmes élevés. Le
livrable a donc été refusé. L'analyse montre que certains tests imposaient des choix absents
de la demande, par exemple l'ordre exact des clés en mode `--keep-last` ou un code d'erreur
générique plutôt qu'un code spécialisé. Un nouvel arbitre QA classe désormais chaque échec
en `implementation_bug`, `test_bug` ou `ambiguous` avant toute modification. Les tests
fautifs sont régénérés sans dégrader le programme ; seuls les défauts d'implémentation
autorisent une correction du code. Les constats critiques ou élevés du gate sont également
soumis à une famille distincte, qui ne peut les invalider que s'ils sont clairement
contredits par le code, la demande, les sources ou les preuves d'exécution.

Le catalogue Model Market a ensuite montré que `kimi-k2.7-code:cloud`, deuxième famille
préférée pour le code, était tombé à 36/100 après une seule tentative d'implémentation
expirée. Cette unique observation l'excluait du groupe des quatre premiers modèles. Code
Forge sélectionne maintenant explicitement Kimi Code comme spécialiste prioritaire de
l'implémentation, avec un timeout de 600 secondes pour les générations longues. Qwen reste
le premier repli ; DeepSeek, GLM et Mistral conservent les rôles indépendants de revue et
d'arbitrage. Les résultats réels continuent d'alimenter Model Market.

Un essai réel suivant a confirmé l'intégration : Kimi Code a produit l'implémentation
Python demandée, la compilation et 57 tests unitaires ont réussi dans Test Forge. Le
livrable a pourtant été refusé à 7/10 parce que le gatekeeper a classé comme élevée une
recommandation de maintenabilité Unicode non reproduite et a ajouté des exigences absentes
de la demande, notamment packaging et documentation future. Le comportement `ß` vers
`ss` relève en Python de `str.casefold()` ; il ne justifie pas un blocage lorsque le
comportement demandé est couvert et passe.

La calibration des revues impose maintenant un registre d'architecture `OBLIGATOIRE`
strictement issu de la demande et un registre `OPTIONNEL` non bloquant. Une sévérité
critique ou élevée doit être reliée à une reproduction en échec, une exigence explicite,
un chemin de sécurité concret ou un risque de perte de données. Le validateur indépendant
retourne aussi catégorie, reproduction et sévérité calibrée. Le code interdit toute hausse
de sévérité et rabaisse automatiquement à moyenne un constat non reproduit de
maintenabilité ou optionnel. Les risques de sécurité, perte de données et violations
explicites restent bloquants même lorsqu'un test automatisé n'est pas pertinent.

## 2026-07-16 — Routage spécialisé et parc Ollama Cloud v2.227

La demande utilisateur ne consiste pas à privilégier Kimi, mais à affecter les meilleurs
modèles Ollama Cloud aux rôles où ils sont réellement les plus utiles. L'audit a montré
que Model Market ne distinguait que six besoins trop larges et que Code Forge forçait
Kimi comme premier implémenteur malgré une télémétrie réelle moins bonne sur cette
installation. Les réglages frontend ignoraient aussi les modèles dont le tag se termine
par `-cloud`, notamment `mistral-large-3:675b-cloud` et `qwen3.5:397b-cloud`.

Model Market distingue désormais conversation générale, raisonnement, agentique,
architecture de code, implémentation, revue, recherche, vérification, synthèse,
productivité, multilingue et vision. Les priorités à froid suivent les capacités annoncées
sur les fiches officielles Ollama : DeepSeek pour le raisonnement et la recherche, GLM
pour l'ingénierie de projet, Kimi Code pour l'implémentation spécialisée, MiniMax M3 pour
l'agentique/navigation/multimodal, Qwen pour la vision et le multilingue, Mistral Large 3
pour la vérification structurée et le français, Nemotron pour le multi-agent et MiniMax
M2.7 pour la productivité. Ces priorités ne sont pas absolues : succès, échecs et latence
des appels réels par phase peuvent changer le classement. À l'instant de la validation,
la télémétrie faisait ainsi passer GLM devant Kimi pour l'implémentation.

Le parc recommandé contient huit modèles complémentaires et ils sont tous déjà accessibles
sur cette installation. Au démarrage, si Ollama Cloud est activé, Marvin appelle
`/api/pull` en arrière-plan uniquement pour les modèles recommandés manquants. Aucun modèle
installé n'est supprimé. Les API `/api/model-market/fleet`, `/fleet/sync` et `/fleet/pull`
exposent l'état, la synchronisation et l'ajout de n'importe quel tag Cloud valide. La page
`/market` présente le parc, permet une synchronisation manuelle et accepte un autre tag
Cloud. Cette solution évite de télécharger systématiquement des générations anciennes ou
retirées, tout en gardant tous les modèles Cloud accessibles à la demande.
La détection couvre aussi les tags Cloud officiels sans suffixe explicite, actuellement
`gemma4:e4b` ; le parc live expose donc neuf modèles Cloud accessibles.

## 2026-07-16 — Test Forge Windows/Linux avec Internet contrôlé v2.228

L'utilisateur demande que Marvin teste réellement ses codes et scripts sous Windows et
Linux, avec accès au Web pour télécharger les dépendances. Deux approches Windows ont été
comparées. Hyper-V avec PowerShell Direct est le meilleur choix pour les scénarios exigeant
redémarrage, pilotes, Active Directory, plusieurs VM ou état persistant, mais nécessite une
image de référence, un compte de VM et une maintenance de checkpoints. Windows Sandbox est
retenu comme runner standard : environnement Windows propre à chaque lancement, faible
maintenance et destruction automatique. Les conteneurs Windows ne sont pas retenus comme
runner principal, car Docker Desktop exécute actuellement un moteur Linux et les images
Windows imposent une compatibilité stricte avec le build hôte.

Le runner Windows génère un `.wsb` par test. Le code, les tests et le bootstrap sont montés
en lecture seule ; seul un répertoire temporaire de résultats est inscriptible. vGPU,
presse-papiers, caméra, microphone et imprimante sont désactivés. Internet reste disponible
pour PSGallery, mais le bootstrap bloque les plages privées IPv4 et IPv6 avant tout
téléchargement. Il installe PSScriptAnalyzer 1.25.0 et Pester 5.8.0, analyse le script puis
exécute les tests. Aucun statut production n'est possible sans résultat JSON complet.

Le diagnostic de la machine établit Windows Pro build 26200, hyperviseur présent, services
Hyper-V `vmms` et `vmcompute` actifs, mais `WindowsSandbox.exe` absent. La fonctionnalité
Windows Sandbox doit donc encore être activée avec privilèges administrateur puis Windows
redémarré. Le script `scripts/prepare-windows-test-forge.ps1` effectue cette activation sans
redémarrage automatique et prend en charge `-WhatIf`; la procédure et le rollback sont dans
`WINDOWS-TEST-FORGE.md`. Jusqu'à cette activation, Marvin continue correctement de refuser
la certification PowerShell au lieu de simuler une exécution.

Sous Linux, le protocole a été renforcé. Le premier passage reste hors ligne pour la syntaxe
et le lint. Lorsqu'Internet est requis, Test Forge copie le livrable dans `/work/src` d'un
Debian 13 jetable, exécute le harness d'installation, puis lance lui-même Bats, unittest ou
node:test. Deux marqueurs distincts sont exigés : intégration fonctionnelle et suite de
tests. Un test réel a utilisé Docker Engine 29.6.1 en mode Linux, exécuté `apt-get update`,
installé Python 3 depuis les dépôts Debian et réussi unittest dans le conteneur. Aucun port,
secret hôte ou socket Docker n'était monté.

### Incident d'activation Windows Sandbox du 17 juillet 2026

Le premier redémarrage a annulé l'activation de Windows Sandbox. Le journal Setup contient
l'événement Servicing 11 avec `0x800F0922`. Le journal CBS donne la cause primaire :
`containerai.dll` échoue à créer la couche de base avec `0x800706D9`, puis la file
d'opérations avancées est annulée. Le journal System confirme que `CmService` ne pouvait
pas démarrer parce que sa dépendance `HvHost` était désactivée. L'état observé dans le
registre était `HKLM\SYSTEM\CurrentControlSet\Services\HvHost\Start=4`.

La correction minimale a remis `HvHost` en démarrage manuel (`Start=3`), sans modifier les
règles de pare-feu ni les réglages VBS/HVCI. Ces derniers restent volontairement désactivés
sur cette machine (`EnableVirtualizationBasedSecurity=0`, HVCI `Enabled=0`) et ne sont pas
requis par Windows Sandbox. Les services RPC, BFE et MpsSvc ont été contrôlés actifs.
L'activation élevée a ensuite réussi et retourné `3010`, ce qui signifie qu'un dernier
redémarrage est nécessaire avant le test Pester réel.

Pour empêcher la récidive, `scripts/prepare-windows-test-forge.ps1` contrôle désormais ces
prérequis, rétablit uniquement `HvHost` de Disabled vers Manual et refuse l'activation si
RPC/BFE/MpsSvc ne sont pas actifs. `WINDOWS-TEST-FORGE.md` documente le diagnostic, DISM/SFC
et le fait que l'Isolation du noyau reste hors périmètre.

### Exigence de distribution Windows

L'utilisateur fixe une contrainte durable : tout Marvin doit pouvoir s'installer simplement
sur tous les Windows pris en charge. La future livraison devra fournir un parcours en un clic,
détecter édition, virtualisation, mémoire, GPU et dépendances, demander l'élévation seulement
pour les actions système, reprendre automatiquement après un redémarrage et produire un
diagnostic actionnable. Windows Sandbox, Hyper-V et Docker restent des accélérateurs ou
runners optionnels ; ils ne doivent pas bloquer l'installation du socle. Une machine sans ces
capacités doit recevoir un état dégradé explicite et conserver les fonctions compatibles.
L'installeur doit également être idempotent, vérifiable et accompagné d'un rollback propre.

### Validation réelle Windows Sandbox après redémarrage

Après redémarrage, `WindowsSandbox.exe` est présent, `HvHost` est actif en démarrage manuel,
et VBS/HVCI restent désactivés. Le premier lancement a déclenché la migration automatique du
client inbox vers Windows Sandbox 0.8.107.0, comportement documenté par Microsoft pour
Windows 11 24H2 et suivants. Cette migration sépare le lanceur historique des processus
réels `WindowsSandboxServer` et `WindowsSandboxRemoteSession`. Le runner ne doit donc jamais
interpréter la sortie du lanceur comme la fin de la VM.

Deux défauts ont été reproduits avant la certification. Premièrement, le répertoire
temporaire était supprimé dès la sortie du lanceur alors que la VM utilisait encore les
montages. Le suivi observe désormais les processus réels, refuse de perturber une Sandbox
déjà ouverte, attend le résultat jusqu'au timeout et ne cible que les processus créés par
Test Forge lors du nettoyage. Deuxièmement, la règle pare-feu invitée bloquant globalement
les réseaux privés coupait le canal de contrôle du client distant ; l'interface affichait
« L'environnement distant se déconnecte ». Le filtre LAN cible maintenant les processus de
test et d'installation, sans bloquer les composants système de la VM.

Un processus `vmmemWindowsSandbox` est resté orphelin après l'interruption manuelle d'un
essai. `scripts/reset-windows-sandbox-admin.ps1` fournit une récupération ciblée en
redémarrant uniquement `CmService`, sans toucher à Docker, WSL ou `vmcompute`. La validation
Pester réelle n'a été revendiquée qu'après libération complète de ce processus.

Le smoke test final `scripts/test_windows_test_runner_live.py` a ensuite réussi en 71,2
secondes. Résultats observés : garde réseau active, parser PowerShell valide, téléchargement
réel de NuGet/PSScriptAnalyzer 1.25.0/Pester 5.8.0 depuis PSGallery, aucun constat
PSScriptAnalyzer et 3/3 tests Pester réussis. Le résultat retourné est
`success=true`, `tests_executed=true`, `production_ready=true`, sans étape en échec. Cette
validation clôt la version 2.229.0 du runner Windows.

## 2026-07-17 — v2.230.0 — Deliverable Bundle et gate de reproductibilité

### Demande

L'installation universelle est reportée. La priorité reste la capacité de Marvin à livrer
du code et des scripts complets, experts, réellement testés et exploitables en production,
tout en conservant une trace portable des technologies et du fonctionnement.

### Constat reproduit

`backend/code_forge.py::extract_code()` ne conservait que le plus grand bloc clôturé. Un
livrable contenant par exemple `main.py`, un module, `pyproject.toml` et des tests perdait
silencieusement les autres fichiers. Test Forge ne recevait ensuite que le point d'entrée et
la suite de tests générée. La validation d'un projet réel multi-fichiers et de ses dépendances
n'était donc pas démontrable, même si le fichier principal était syntaxiquement valide.

### Décisions

- Ajout d'un contrat `Deliverable Bundle` limité à 48 fichiers, 200 000 octets par fichier
  et 800 000 octets par bundle.
- Format multi-fichiers explicite : un bloc clôturé par fichier avec
  `file=chemin/relatif`; les points d'entrée sont `main.py`, `main.ps1`, `main.sh`,
  `main.mjs` ou `main.json`.
- Refus déterministe des chemins absolus Windows/Unix, traversées `..`, doublons,
  `.git`, `.svn`, `node_modules`, `.venv`, NUL et chemins excessifs.
- Contrôle de reproductibilité : un projet npm avec dépendances doit contenir un
  `package-lock.json` ou `npm-shrinkwrap.json` JSON valide avec `lockfileVersion`; un projet
  Python avec dépendances doit contenir un `pylock.toml` TOML valide ou un fichier de
  requirements intégralement épinglé avec `==`.
- Le bundle complet est transmis aux deux reviewers, au gatekeeper, au générateur de tests
  et à Test Forge. Le retour API expose désormais `files` et les métadonnées du bundle.
- Les runners Docker reconstruisent toute l'arborescence dans le workspace jetable. Les
  validations PowerShell locales et Windows Sandbox parcourent récursivement `.ps1` et
  `.psm1`, au lieu d'analyser uniquement `main.ps1`.

### Fichiers créés ou modifiés

- `backend/deliverable_bundle.py`
- `backend/code_forge.py`
- `backend/test_forge.py`
- `backend/windows_test_runner.py`
- `scripts/test_deliverable_bundle.py`
- `scripts/test_code_forge.py`
- `scripts/test_test_forge.py`
- `scripts/test_windows_test_runner.py`
- `scripts/check_marvin.py`
- `scripts/check_architecture.py`
- `package.json`, `package-lock.json`, `backend/app_version.py`, `backend/main.py`
- `README.md`, `AGENTS.md`, `DEVELOPMENT-JOURNAL.md`

### Validation observée

- Compilation Python de `deliverable_bundle.py`, `code_forge.py`, `test_forge.py` et
  `windows_test_runner.py` : réussie.
- `scripts/test_deliverable_bundle.py` : réussi, incluant multi-fichiers Python, verrou,
  absence de verrou npm, traversal et chemin absolu Windows.
- `scripts/test_code_forge.py` : réussi avec un bundle simulé à trois fichiers transmis à
  Test Forge et refus déterministe d'un projet Python non verrouillé.
- `scripts/test_test_forge.py` : réussi, incluant refus d'un fichier auxiliaire traversant
  et blocage production d'un projet Python non verrouillé.
- `scripts/test_windows_test_runner.py` : réussi après extension du runner aux fichiers
  PowerShell auxiliaires.

### Contrôle final

`scripts/check_marvin.py --quick` réussit intégralement en v2.230.0 : runtime Node et modules
natifs, 340 outils, 316 routes, 38 pages, 60 outils encadrés, toutes les régressions Forge,
cohérence des dépendances et compilation de 84 fichiers Python. ESLint termine avec 0 erreur
et 37 avertissements préexistants.

Le nouveau smoke live Windows Sandbox a été demandé après la modification récursive, mais
l'autorisation d'exécution externe a été refusée par la limite d'usage Codex du poste. Aucun
contournement n'a été tenté. La preuve live v2.229 reste valable pour le runner mono-fichier ;
la variante récursive v2.230 est couverte par compilation et tests déterministes mais son
nouveau passage Sandbox réel reste explicitement à exécuter avec
`npm run check:windows-test-forge-live` lorsque l'autorisation sera de nouveau disponible.

Le backend en cours expose encore v2.229.0. Sa relance contrôlée vers v2.230.0 a elle aussi été
refusée avant exécution par la même limite d'autorisation ; aucun processus n'a été modifié.

### Complément de validation v2.230

Après autorisation explicite de l'utilisateur, le smoke réel Windows Sandbox a finalement
réussi en 92,5 secondes, dont 75,0 secondes mesurées dans le runner. Résultat observé :
`success=true`, `production_ready=true`, `tests_executed=true`, aucun échec, parser récursif
valide, PSScriptAnalyzer 1.25.0 sans constat et Pester 5.8.0 avec 3/3 tests. Le backend a
ensuite été relancé proprement et `/api/health` a exposé la version 2.230.0.

## 2026-07-17 — v2.231.0 — Production Contract Gate

### Objectif

Poursuivre l'amélioration de la qualité de livraison après Deliverable Bundle. Une note de
reviewer et une syntaxe valide ne suffisent pas pour revendiquer un livrable exploitable en
production : Marvin doit transporter des preuves déterministes supplémentaires.

### Conception retenue

Deux approches ont été comparées. Installer systématiquement des analyseurs supplémentaires
depuis Internet dans chaque test apporterait un typage plus profond, mais augmenterait
latence, fragilité réseau et surface de dépendances. Le gate retenu complète les runners
existants avec des contrôles déterministes locaux, puis exige la preuve d'intégration réseau
déjà isolée lorsque le projet possède des dépendances externes. Cette architecture conserve
un résultat reproductible sans transformer tout script simple en projet complexe.

Le nouveau `backend/production_contract.py` vérifie :

- présence et inventaire de toutes les sources ;
- preuve d'analyse statique issue du runner correspondant au langage ;
- exécution d'une suite de tests comportementaux ;
- annotations de tous les paramètres et retours des fonctions Python publiques ;
- preuve d'installation en environnement jetable lorsque des dépendances existent ;
- génération d'un SBOM CycloneDX 1.6 déterministe depuis `package-lock.json`,
  `npm-shrinkwrap.json`, `pylock.toml` ou des requirements épinglés.

Code Forge inclut ce gate dans sa décision finale et expose son rapport et son SBOM. Test
Forge compile désormais récursivement tous les `.py`, vérifie tous les `.js/.mjs/.cjs` et
conserve l'analyse récursive PowerShell ajoutée en v2.230. Un nom de fichier contenant un
caractère de contrôle est également refusé avant création du workspace.

### Validation observée

- `scripts/test_production_contract.py` : réussi pour Python typé, rejet Python non typé,
  absence de preuve d'installation et SBOM npm/Python.
- `scripts/test_code_forge.py` : réussi avec le gate intégré au verdict final.
- `scripts/test_test_forge.py` : réussi sans Docker.
- `scripts/test_test_forge_live_bundle.py` : réussi avec Docker réel. Un bundle Python
  multi-fichiers valide a exécuté unittest ; un second bundle contenant une erreur de syntaxe
  uniquement dans `src/broken.py` a été correctement refusé par `python_compile`.
- `scripts/check_marvin.py --quick` : 22/22 étapes réussies, 85 fichiers Python compilés,
  340 outils, 316 routes, 38 pages, ESLint avec 0 erreur et 37 avertissements préexistants.
- Backend relancé : `/api/health` expose réellement `2.231.0` ; frontend HTTP 200.

### Sources de conception

- PyPA : `pyproject.toml` et `pylock.toml` pour les métadonnées et installations
  reproductibles.
- npm CLI : `npm sbom` produit CycloneDX ou SPDX depuis le graphe npm.
- CycloneDX : schéma officiel et validation des BOM structurées.
- NIST SSDF : automatisation des vérifications et suivi des composants logiciels.

## 2026-07-17 — v2.232.0 — Go Forge et Advanced Coding Mission

### Demande

Marvin doit pouvoir étendre sa génération à tout type de code Windows/Linux et exceller sur
les tâches longues de coding avancé. La contrainte est interprétée sans survente : une
toolchain n'est marquée `certified` que si Marvin dispose d'un runner réel et de preuves ;
les langages futurs restent visibles mais `planned`.

### Matrice de langages

`backend/language_registry.py` centralise désormais langage, alias, systèmes réellement
testés, compilations croisées, version de toolchain et contrôles disponibles. Python,
PowerShell, Bash, JavaScript, JSON et Go sont certifiés sur leurs cibles réellement exécutées.
TypeScript 6.0, Rust 1.97.0, .NET 10 LTS, Java et C++ sont planifiés et ne peuvent pas être
présentés comme validés production avant ajout de leur runner.

Go utilise l'image officielle `golang:1.26.5-bookworm` épinglée au digest
`sha256:1ecb7edf62a0408027bd5729dfd6b1b8766e578e8df93995b225dfd0944eb651`.
Le runner impose réseau désactivé, racine en lecture seule, utilisateur 65534, capacités
supprimées, 1 Gio de RAM, CPU borné et tmpfs dédiés. Il exécute `gofmt`, `go vet`, `go test`
et une compilation `GOOS=windows GOARCH=amd64`. Le résultat Windows est donc une preuve de
cross-compilation, pas une preuve d'exécution Windows.

### Incidents utiles du smoke Go

Le premier essai a détecté un test non formaté et l'absence de cache Go inscriptible. Le
deuxième a établi que 64 Mio de tmpfs étaient insuffisants. Le troisième a compilé et passé
`go vet`, mais le binaire de test était bloqué par `/tmp` en `noexec`. La correction finale
conserve `/tmp` non exécutable et place uniquement `GOTMPDIR` dans `/work`, tmpfs exécutable,
borné et non persistant. Le smoke final réussit `gofmt`, `go vet`, `go test`, Production
Contract et cross-build Windows.

### Coding longue durée

`backend/coding_mission.py` crée un espace local par mission avec écriture atomique,
événements append-only, révisions optimistes et snapshots JSON du bundle. Chaque fichier
porte taille et SHA-256. Les phases couvrent planification, architecture, implémentation,
revue, tests, réparation, acceptation, échec et pause. Code Forge crée automatiquement une
mission pour les projets longs/multi-fichiers, enregistre les phases et renvoie `mission_id`.
Une nouvelle invocation avec cet identifiant recharge le dernier snapshot, ce qui permet de
reprendre après interruption sans recommencer depuis zéro. Les secrets connus sont expurgés
des états et les mêmes limites de chemins/taille que Deliverable Bundle restent appliquées.

### Validations observées

- `scripts/test_go_forge_live.py` : réussi dans Docker réel avec Go 1.26.5 et cross-build.
- `scripts/test_language_matrix.py` : séparation certifié/planifié et cibles vérifiée.
- `scripts/test_coding_mission.py` : snapshots, reprise, expurgation et conflit de révision.
- Régressions Code Forge, Deliverable Bundle, Test Forge et Production Contract : réussies.
- Contrôle global : 24/24 étapes, 87 fichiers Python compilés, 340 outils, 316 routes,
  38 pages, ESLint 0 erreur et 37 avertissements préexistants.
- Backend relancé : `/api/health` expose `2.232.0` ; frontend HTTP 200.

### Sources officielles

- Go Release History : Go 1.26.5 publié le 7 juillet 2026 avec correctifs de sécurité.
- Rust Release Announcements : Rust 1.97.0 publié le 9 juillet 2026.
- Microsoft .NET releases and support : .NET 10 LTS jusqu'en novembre 2028.
- TypeScript 6.0 release notes : version de transition publiée en juillet 2026.

## 2026-07-17 — v2.233.0 — Engineering Knowledge Radar

### Demande

Marvin doit rester informé des versions, conventions et changements des langages afin que
Code Forge ne dépende pas uniquement des connaissances figées des modèles. La solution doit
reprendre les pratiques utiles des meilleurs agents de code sans charger toute la
documentation dans chaque prompt ni autoriser une page distante à piloter des outils.

### Décision et alternatives

Deux approches ont été comparées. Un corpus complet indexé en permanence maximise la
couverture mais augmente le bruit, le coût de contexte, les données périmées et la surface
d'injection. Une récupération libre sur le Web est plus souple mais ne garantit ni autorité
ni reproductibilité. La solution retenue est un radar à catalogue fermé : sources officielles
allowlistées, cache local, détection de changement et sélection à la demande par langage.

Cette approche reprend les mécanismes observés chez les agents de code modernes : instructions
de dépôt persistantes (`AGENTS.md`, fichiers d'instructions ciblés), récupération du contexte
pertinent, outils spécialisés, boucle test/correction et accès contrôlé aux documentations.
Marvin ajoute une preuve SHA-256, une dette de fraîcheur et un firewall de contenu observé.

### Implémentation

- `backend/engineering_radar.py` : 19 sources officielles pour dix familles, cadence de 72 à
  720 heures, requêtes conditionnelles ETag/Last-Modified, limite 4 Mio, validation stricte du
  domaine final, extraction bornée, SHA-256, événements append-only et worker toutes les 6 h.
- Les blocs documentaires portent explicitement `UNTRUSTED_OFFICIAL_DOCUMENTATION`; les
  instructions détectées dans une page restent des données et ne peuvent autoriser un outil.
- `backend/code_forge.py` : injection de la documentation uniquement pour les langages détectés
  dans l'architecture, les réparations, le gate final et la validation des constats. Une Coding
  Mission conserve les identifiants et hashes des sources utilisées.
- `backend/api/knowledge.py` : état de fraîcheur en lecture et actualisation respectant la
  cadence. Aucun URL arbitraire et aucun contournement `force` ne sont exposés par HTTP.
- `scripts/test_engineering_radar.py` : cache, hash, détection des langages, fraîcheur et phrase
  d'injection inerte. `scripts/test_engineering_radar_live.py` : téléchargement réel des deux
  documentations Go officielles.

### Validations observées

- Test déterministe Engineering Knowledge Radar : réussi.
- Test Code Forge : réussi et présence du bloc documentaire confirmée dans le prompt réel mocké.
- Smoke réseau : documentation Go Release History et Effective Go téléchargée, extraite et
  vérifiée avec deux hashes SHA-256.
- Contrôle d'architecture intermédiaire : 340 outils, 318 routes et 38 pages.
- Validation consolidée `scripts/check_marvin.py --quick` : 25/25 étapes réussies, 88 fichiers
  Python compilés, dépendances cohérentes et ESLint sans erreur (37 avertissements préexistants).
- Backend relancé : `/api/health` expose `2.233.0`; l'API Radar retourne deux sources Go
  disponibles et fraîches; frontend Turbopack HTTP 200.

### Sources de conception

- [GitHub Copilot repository instructions](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions-in-your-ide/add-repository-instructions-in-your-ide?tool=visualstudio)
- [GitHub Copilot custom instructions support](https://docs.github.com/en/copilot/reference/custom-instructions-support)
- [GitHub Copilot code review and MCP](https://docs.github.com/en/copilot/concepts/agents/code-review)
- [OpenAI — How OpenAI uses Codex](https://cdn.openai.com/pdf/6a2631dc-783e-479b-b1a4-af0cfbd38630/how-openai-uses-codex.pdf)
- [Go release history](https://go.dev/doc/devel/release)
- [TypeScript 6.0 release notes](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-6-0.html)
- [Rust release announcements](https://blog.rust-lang.org/releases/)
- [.NET releases and support](https://learn.microsoft.com/en-us/dotnet/core/releases-and-support)

## 2026-07-17 — v2.234.0 — Code Workspace

### Demande et analyse comparative

L'utilisateur propose un onglet dédié au code pour améliorer visibilité et suivi des projets.
Trois options ont été comparées : ajouter un éditeur web complet, étendre Forge, ou créer un
centre de supervision distinct. L'éditeur intégré dupliquerait VS Code, augmenterait fortement
la maintenance et confondrait édition manuelle avec certification. Forge doit rester un banc
de mesure indépendant. La solution retenue est donc un Workspace centré sur les missions.

Les interfaces de référence convergent sur cette organisation. Codex présente un command
center multi-projets avec tâches longues, worktrees isolés, revue des changements et skills.
GitHub Copilot expose sessions parallèles, fichiers lus/modifiés, tests, steering et revue ;
ses agents spécialisés séparent exploration, exécution et code review dans des contextes
distincts. Marvin conserve cette séparation tout en affichant ses preuves Test Forge et la
fraîcheur documentaire dans la même vue projet.

### Implémentation

- `app/code/page.jsx` et `code.module.css` : création d'une mission préparée dans le chat,
  compteurs, liste de projets, phases, révisions, cibles, fichiers, hashes, aperçu du code,
  chronologie, capacités certifiées et sources du Knowledge Radar.
- `backend/coding_mission.py` : inventaire durable, événements et manifeste du dernier
  snapshot sans charger tous les contenus dans la liste.
- `backend/api/coding.py` : API de supervision en lecture seule. Le contenu d'un fichier
  n'est retourné que pour un chemin exact présent dans le snapshot.
- `app/api/coding/[...path]/route.js` : proxy Next.js GET borné pour supprimer la dépendance
  du navigateur à un accès direct au port 8005, notamment en LAN.
- `components/chat/ChatContainer.jsx` : le Workspace prépare un brouillon local, mais ne
  l'envoie jamais automatiquement. La reprise transmet explicitement le `mission_id`.
- Barre latérale et smoke test des pages étendus à `/code`; contrats live backend et proxy
  ajoutés au smoke test HTTP.

### Vérifications intermédiaires observées

- Compilation Python et test Advanced Coding Mission : réussis.
- ESLint ciblé sur Code Workspace, ChatContainer et Sidebar : aucune erreur.
- Contrôle d'architecture : 340 outils, 322 routes, 39 pages.
- Backend v2.234 démarré; `/api/coding/overview` retourne 11 langages et les sources Radar.
- Proxy Next.js `/api/coding/overview` : contrat identique au backend.
- Inspection visuelle réelle : hiérarchie, densité, responsive CSS et état vide cohérents.
- Validation consolidée : 25/25 étapes, 89 fichiers Python compilés, 340 outils, 322 routes,
  39 pages et ESLint sans erreur (37 avertissements préexistants).
- Smoke HTTP live : 26/26 contrats, incluant backend Coding Workspace et proxy Next.js.
- Santé finale : backend `2.234.0`, frontend Turbopack HTTP 200 et `/code` HTTP 200.

### Sources officielles utilisées

- [OpenAI — Introducing the Codex app](https://openai.com/index/introducing-the-codex-app/)
- [GitHub — Working with agent sessions](https://docs.github.com/en/copilot/how-tos/github-copilot-app/agent-sessions)
- [GitHub — Managing agent sessions](https://docs.github.com/en/enterprise-cloud%40latest/copilot/how-tos/copilot-on-github/use-copilot-agents/manage-and-track-agents)
- [GitHub — Custom agents and sub-agent orchestration](https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/custom-agents)

## 2026-07-17 — v2.235.0 — Repository Intelligence, Auto borné et routage Windows

### Demande

Rendre Marvin autonome pour le développement comme Claude Code ou Codex, avec une qualité
supérieure par l'exécution systématique du code en conteneur ou VM, notamment pour les
applications Windows, et exposer un vrai mode Auto dans Code Workspace.

### Décisions

- Retenir l'autonomie supervisée : exécution autonome dans un worktree Git isolé, budgets
  bornés et confirmation conservée pour les actions externes, irréversibles ou nécessitant
  un secret.
- Lire les instructions proches du dépôt (`AGENTS.md`, `CLAUDE.md`) par portée, sans exécuter
  le projet pendant l'analyse et sans lire `.env`, clés ou certificats.
- Exiger une preuve native par cible. Une cross-compilation ou un lint ne permet pas de
  déclarer un livrable Windows prêt pour la production.
- Router PowerShell vers Windows Sandbox; réserver CLI/service, desktop, installateurs et
  pilotes aux futurs runners Windows/Hyper-V correspondants, avec refus de certification
  tant qu'ils ne sont pas disponibles.

### Fichiers

- `backend/repository_intelligence.py` : inventaire borné, Git, manifests, lockfiles, scripts,
  README et chaîne d'instructions avec empreinte de contrat.
- `backend/coding_workspace.py` : création confirmée d'une branche et d'un worktree isolés,
  état et diff borné.
- `backend/windows_validation.py` : sélection déterministe du backend Windows requis.
- `backend/api/coding.py`, `app/api/coding/[...path]/route.js`, `app/code/page.jsx` : analyse,
  création de mission Auto et supervision du worktree.
- `scripts/test_repository_intelligence.py` : dépôt Git temporaire, secret exclu, règles
  hiérarchiques, isolation réelle et routage Windows.

### Validations réelles

- Compilation Python ciblée : réussie.
- ESLint ciblé Code Workspace et proxy : réussi.
- Régressions Repository Intelligence : réussies sur un dépôt Git temporaire réel.
- Régressions Advanced Coding Mission : réussies.
- Validation consolidée : 26/26 étapes, 92 fichiers Python compilés, 340 outils, 327 routes,
  39 pages, aucune erreur ESLint et 37 avertissements préexistants.
- Backend redémarré en `2.235.0`; frontend Turbopack et `/code` répondent HTTP 200.
- Analyse Repository Intelligence réelle de Marvin réussie directement et via le proxy Next.
- Routage WPF observé vers `windows_gui_vm` avec certification refusée tant que ce runner
  natif n'est pas disponible; smoke HTTP live 26/26 contrats.

### Références officielles

- [OpenAI — Codex best practices](https://learn.chatgpt.com/guides/best-practices)
- [OpenAI — AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Anthropic — Run parallel sessions with worktrees](https://code.claude.com/docs/en/worktrees)
- [Anthropic — Create custom subagents](https://code.claude.com/docs/en/sub-agents)
- [Anthropic — Hooks](https://code.claude.com/docs/en/hooks-guide)
- [Microsoft — Configurer Windows Sandbox](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file)
- [Microsoft — PowerShell Direct](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/powershell-direct)
- [Microsoft — Checkpoints Hyper-V](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/checkpoints)

## 2026-07-17 — v2.236.0 — Superviseur Auto persistant

### Demande

Poursuivre l'autonomie de Marvin afin qu'une mission de code fonctionne comme un agent
Codex/Claude Code : exécution autonome, tests obligatoires, arrêt, reprise et conservation de
l'état, sans modifier directement le dépôt utilisateur.

### Architecture retenue

- `coding_jobs.py` persiste les jobs dans `data/coding_jobs.json`; une seule mission lourde
  s'exécute à la fois pour éviter la concurrence sur Ollama, Docker et Windows Sandbox.
- Au démarrage FastAPI, les états `queued`, `running` et `interrupted` reprennent avec le temps
  et les tentatives déjà consommés. L'arrêt du backend marque le job `interrupted` avant de
  l'annuler.
- Repository Intelligence transmet les règles `AGENTS.md`/`CLAUDE.md` comme instructions de
  projet et encapsule tous les autres fichiers comme données non fiables. Le volume et le
  nombre de fichiers sont bornés; secrets et lockfiles volumineux sont exclus du contenu.
- Code Forge réalise architecture, implémentation, revues, réparations et Test Forge. Un
  livrable accepté est appliqué transactionnellement dans le worktree. Toute erreur restaure
  les fichiers précédents; `.git`, liens symboliques et sorties du worktree sont refusés.
- La mission ne devient `completed` que si toutes les cibles sont exécutées. Une cible Windows
  sans runner natif adapté produit `blocked/paused`, même si le build croisé réussit.

### Interface et API

- Code Workspace démarre réellement le job Auto sans renvoi dans le chat et affiche état,
  étape, progression, tentative, temps consommé, erreur, arrêt et reprise.
- API : liste/détail des jobs et actions `cancel`/`resume`; le détail d'une Coding Mission
  contient son dernier job Auto.

### Validations réelles

- Dépôt Git temporaire : contexte borné, application dans le seul worktree et checkout source
  inchangé.
- Superviseur simulé sans cloud : job terminé, résultat appliqué, annulation, mission pausée,
  état interrompu puis reprise du même job jusqu'à `completed`.
- Validation consolidée : 27/27 étapes, 93 fichiers Python compilés, 340 outils, 331 routes,
  39 pages, aucune erreur ESLint et 37 avertissements préexistants.

### Ajustement de politique demandé

Le plafond initial de 120 minutes était ambigu. Il est remplacé sémantiquement par une tranche
`time_slice_minutes` : la mission porte `completion_policy=until_success` et ne possède pas de
date d'expiration. Une erreur récupérable déclenche un backoff puis une nouvelle tentative avec
le même job. Les retries restent bornés à trois échecs consécutifs afin d'éviter une boucle de
coût infinie; au-delà, le job reste durable en `blocked` et reprend après résolution humaine.
Une régression simule échec temporaire puis réussite automatique à la tentative suivante.

### Activation live

- Backend redémarré en `2.236.0`; frontend Turbopack et `/code` répondent HTTP 200.
- Contrats live `GET /api/coding/jobs`, OpenAPI cancel/resume et proxy Coding vérifiés.
- Smoke HTTP complet : 26/26 contrats. Aucun job cloud ni worktree utilisateur créé pendant
  la validation live.

## 2026-07-17 — v2.237.0 — Runner Windows natif Hyper-V

### Demande

Poursuivre la certification des applications Windows produites par Marvin dans une vraie VM,
avec exécution et tests natifs avant livraison, sans rendre Marvin plus fragile ni exposer le
réseau local.

### Diagnostic réel de cette machine

- Les services Hyper-V `vmms` et `HvHost` sont installés; le module PowerShell Hyper-V est
  disponible et Windows Sandbox est présent.
- Le processus Marvin courant n'a pas l'autorisation d'interroger `Get-VM` : l'inventaire des
  VM et checkpoints n'a donc pas pu être validé.
- Aucune VM ni aucun checkpoint n'a été créé, modifié ou supprimé. Le backend doit annoncer
  `ready=false` tant qu'une VM existante n'est pas configurée et accessible.

### Architecture retenue

- `hyperv_test_runner.py` inspecte une VM et son checkpoint, les restaure avant et après les
  tests, déconnecte les cartes réseau pendant l'exécution et transporte les fichiers par
  PowerShell Direct, sans partage SMB, port invité ni socket Docker.
- Le compte invité doit être non administrateur. Une exécution réussie avec un compte
  administrateur reste `production_ready=false`.
- Le secret invité est chiffré avec Windows DPAPI dans `data/windows_secrets.dpapi.json`; le
  mot de passe en clair n'est jamais renvoyé par l'API ni conservé dans la configuration.
- Le premier niveau Hyper-V est volontairement hors ligne. Les toolchains et dépendances
  requises doivent exister dans le checkpoint propre. Un futur niveau Internet contrôlé sera
  distinct, avec filtrage de sortie et blocage explicite des réseaux privés.
- Le superviseur Auto appelle ce runner pour Python, JavaScript/TypeScript, Go, C#, Rust et
  Java quand le routage exige `windows_cli_vm`. Une absence de preuve native bloque la mission
  au lieu de maquiller un cross-build en certification Windows.

### Interface, API et exploitation

- Code Workspace contient un onglet `Windows VM` affichant backend, VM, checkpoint, secret,
  réseau et erreur d'accès; il peut associer une VM existante après confirmation explicite.
- API : `GET /api/coding/validation/windows/hyperv` et
  `POST /api/coding/validation/windows/hyperv/configure`.
- `scripts/prepare-hyperv-test-forge.ps1` est en audit seul par défaut. L'ajout au groupe
  Hyper-V Administrators ou la création d'un checkpoint existant exigent `-Confirm`.
- La procédure d'exploitation, le rollback et les limites sont décrits dans
  `HYPERV-TEST-FORGE.md`.

### Validations réelles

- Roundtrip DPAPI natif réussi; le secret en clair est absent du fichier persistant.
- Régressions simulées : statut/configuration, enveloppe PowerShell Direct, checkpoint avant
  et après, réseau coupé, compte non administrateur et refus du compte administrateur.
- Analyse syntaxique PowerShell du script de préparation : réussie.
- Validation consolidée : 28/28 étapes, 95 fichiers Python compilés, 340 outils, 333 routes,
  39 pages, aucune erreur ESLint et 37 avertissements préexistants.
- Limite explicite : aucune exécution dans une VM réelle n'a été possible sans VM accessible;
  la certification Hyper-V live n'est donc pas revendiquée.

### Activation du compte hôte

- Le compte interactif `Chawb` est administrateur local, mais Marvin doit continuer à être
  lancé sans élévation. Le rôle local `Administrateurs Hyper-V` lui donne uniquement l'accès
  courant à Hyper-V sans conférer ces privilèges aux 340 outils du processus.
- Le terminal Codex fonctionne sous l'identité isolée `CodexSandboxOffline`; il ne peut pas
  modifier les groupes locaux ni hériter du jeton administrateur de `Chawb`.
- `ACTIVER-HYPERV-MARVIN.bat` est fourni pour l'unique action manuelle restante : double-clic,
  acceptation UAC, ajout du compte interactif, preuve JSON et renouvellement de session.
- L'activateur mesure l'état des cartes physiques avant et après et annonce
  `host_network_modified=false`. Le runner ne déconnecte que l'adaptateur virtuel de la VM.
- Correctif d'activation : `powershell.exe -File` interprétait `-Confirm:$false` comme une
  chaîne CMD incompatible avec `SwitchParameter`. L'activateur utilise désormais son drapeau
  obligatoire `-Confirmed`; le script conserve `SupportsShouldProcess` et le mode `-WhatIf`.
- Après redémarrage, le jeton de `Chawb` contient effectivement le groupe Hyper-V et le Wi-Fi
  reste actif. `vmms`, `HvHost`, Ollama, FastAPI et Turbopack sont opérationnels.
- La couche CIM voit douze anciennes VM arrêtées, mais `Get-VM` ne peut lire aucune
  configuration. `Get-VMHost` pointe vers `C:\\Hyper-V\\`, aujourd'hui absent, et VMMS journalise
  au moins une inscription orpheline (`RODC`). Aucune ancienne VM n'a été modifiée.
- Un ISO Windows Server Evaluation local a été identifié et haché, mais n'a pas été monté
  ni utilisé. Les ISO `unattend` existants ciblent Windows 11 Pro et contiennent des valeurs
  d'identification; ils sont incompatibles avec cette image Server et ne seront pas réutilisés.
- L'audit Hyper-V élevé en lecture seule n'a produit aucune preuve avant expiration de l'UAC;
  aucun provisionnement n'est revendiqué.

### Références officielles

- [Microsoft — Configuration Windows Sandbox et risque réseau](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file)
- [Microsoft — Exigences Hyper-V](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/host-hardware-requirements)
- [Microsoft — Gérer Hyper-V avec PowerShell](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/powershell)
- [Microsoft — Checkpoints Hyper-V](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/checkpoints)
- [Microsoft — PowerShell Direct](https://learn.microsoft.com/en-my/windows-server/virtualization/hyper-v/powershell-direct)
- [Microsoft — NAT Hyper-V](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/setup-nat-network)

## 2026-07-17 — v2.238.0 — Chemins Windows portables

### Demande

Supprimer les dépendances aux chemins de la machine de développement afin que Marvin puisse
migrer et s'installer sur d'autres PC Windows sans correction manuelle du nom d'utilisateur,
de la lettre du volume ou des dossiers redirigés.

### Constats

- Les données applicatives et les nouveaux runners utilisaient déjà des racines calculées,
  mais la documentation MCP contenait encore un chemin absolu propre à cette installation.
- Plusieurs sorties par défaut construisaient `Desktop`, `Documents` et `Downloads` sous le
  profil. Cette hypothèse devient fausse avec OneDrive, une GPO de redirection ou une langue
  Windows différente.
- Des placeholders d'interface citaient le compte de développement et favorisaient la copie
  de chemins non portables.

### Solution

- `backend/platform_paths.py` utilise `SHGetKnownFolderPath` pour le profil, Bureau,
  Documents, Téléchargements, Images, Musique, Vidéos, AppData et Démarrage. Les variables
  d'environnement et des replis multi-plateformes sont conservés.
- `tools.py` et `/api/system/paths` partagent cette source unique. Les sorties automatiques
  et les accès rapides suivent maintenant les redirections réelles.
- Les alias `Bureau\\fichier`, `Documents\\fichier` et `%VARIABLE%` sont acceptés puis
  convertis en chemins absolus au moment de l'exécution.
- `mcp_server.py --print-config` génère le JSON MCP avec les chemins absolus de l'installation
  courante; aucun chemin utilisateur n'est conservé dans le code.
- Les ressources externes futures, notamment ISO/VHDX Hyper-V, seront des paramètres machine
  validés. La valeur par défaut de stockage Hyper-V sera calculée depuis `%ProgramData%` et
  non fixée à `C:\\Hyper-V`.

### Validations réelles

- Régressions Known Folders, alias, sous-chemins et variables d'environnement : réussies.
- Compilation de `platform_paths.py`, `tools.py`, `api/content.py` et `mcp_server.py` : réussie.
- Génération MCP réelle : chemins calculés depuis la racine actuelle et JSON valide.
- Contrôle d'architecture : Marvin `2.238.0`, 340 outils, 333 routes et 39 pages.
- ESLint ciblé : aucune erreur; trois avertissements préexistants dans l'onglet Outils.
- Validation consolidée finale : 29/29 étapes, 96 fichiers Python compilés, aucune erreur
  ESLint et 37 avertissements préexistants sur l'ensemble du frontend.
- Backend redémarré en `2.238.0`; frontend Turbopack et `/code` répondent HTTP 200.
- API live : Bureau, Documents et Téléchargements correspondent aux Known Folders du profil
  courant; smoke HTTP complet 26/26 contrats.

## 2026-07-17 — v2.239.0 — Bibliothèque technique et exports Marvin

### Demande

Classer durablement les besoins de Marvin : ISO, VM, documents générés, code, artefacts de
tests et ressources futures, sans introduire de chemins propres à cette machine.

### Constats et décision

- Un répertoire unique sous Documents ou OneDrive mélangerait VHDX/ISO et livrables, avec
  risques de synchronisation, contention, consommation de quota et performances dégradées.
- Deux racines sont retenues : une bibliothèque locale machine pour les ressources lourdes
  et temporaires, et une racine d'exports utilisateur résolue par Known Folder.
- La bibliothèque machine refuse les lecteurs réseau et les racines cloud détectées. Les
  racines restent configurables et ne codent ni utilisateur ni lettre de lecteur.

### Solution

- `backend/storage_layout.py` définit l'arborescence, valide le volume, mesure l'espace libre,
  crée les dossiers de manière idempotente et inventorie les ISO Windows/Linux.
- `backend/api/storage.py` expose l'état, la création confirmée et la configuration confirmée.
- `/code` reçoit un onglet Bibliothèque via un proxy Next.js dédié; il affiche les chemins,
  l'espace libre et les ISO classées.
- Racines créées réellement sur cette installation :
  `C:\Users\Chawb\AppData\Local\Marvin` et `C:\Users\Chawb\Documents\Marvin`.

### Validations réelles

- Test ciblé de séparation, confirmation, inventaire et refus réseau : réussi.
- Compilation Python ciblée : réussie.
- ESLint sans avertissement autorisé (`--quiet`) : réussi.
- Validation consolidée : 30/30 étapes, 98 fichiers Python compilés, 340 outils, 336 routes,
  39 pages, aucune erreur ESLint et 37 avertissements préexistants.
- Backend redémarré en `2.239.0`; frontend Turbopack et `/code` répondent HTTP 200.
- Smoke HTTP live : 27/27 contrats, y compris API et proxy de bibliothèque.
- Parcours Playwright réel : onglet Bibliothèque activé, deux racines et espace libre affichés;
  capture `artifacts/tests/code-library-v2239.png` vérifiée visuellement dans la bibliothèque.

## 2026-07-17 — v2.240.0 — VM Lab, médias certifiés et provisionnement Hyper-V

### Demande

Classer les ISO Windows/Linux téléchargées, poursuivre le VM Lab et supprimer les anciennes VM
devenues inutiles sans fragiliser Marvin ni couper le réseau de l'hôte.

### Médias et preuves

- `Win11_25H2_French_x64_v2.iso` déplacée dans `library/iso/windows`; SHA-256
  `A02693BEB8EB166AFDFDB7DB49176A2B547F81E61030A695FE172277DB6A1977`, identique à Microsoft.
- `debian-13.6.0-amd64-netinst.iso` déplacée dans `library/iso/linux`; SHA-512 identique au
  manifeste officiel Debian `current/amd64/iso-cd/SHA512SUMS`.
- `vm_lab.py` conserve chemin, taille, `mtime_ns`, algorithme et empreinte. Une modification du
  fichier invalide immédiatement la preuve mémorisée.

### Provisionnement réel

- `Marvin-Windows11-TestForge` créée arrêtée : génération 2, 6 Gio, 4 vCPU, VHDX dynamique
  80 Gio, Secure Boot `MicrosoftWindows`, vTPM actif, ISO attachée.
- `Marvin-Debian13-TestForge` créée arrêtée : génération 2, 4 Gio, 4 vCPU, VHDX dynamique
  40 Gio, Secure Boot `MicrosoftUEFICertificateAuthority`, ISO attachée.
- Checkpoints automatiques désactivés; type `ProductionOnly`; `Default Switch` attaché pour
  l'installation. La carte physique Wi-Fi est restée `Up` et inchangée.

### Anciennes VM

- L'inventaire global retourne les deux VM Marvin et douze erreurs provenant d'inscriptions
  historiques cassées. Les anciens noms ne sont plus accessibles comme objets et aucun VHD
  historique n'a donc été supprimé aveuglément.
- `remove-legacy-hyperv-vms.ps1` préserve les noms `Marvin-*`, journalise les disques attachés
  et a produit `blocked_corrupt_inventory`. Le nettoyage des douze liens fantômes exige un
  audit administrateur du magasin Hyper-V; `audit-hyperv-store-admin.ps1` est prévu à cet effet.
- L'élévation lancée depuis le processus Codex n'a pas produit le rapport UAC. Le lanceur manuel
  `AUDITER-MAGASIN-HYPERV.bat` a été ajouté; aucune suppression aveugle de `ProgramData` n'est faite.
- L'audit administrateur manuel a ensuite confirmé 14 caches VM : les deux GUID Marvin et douze
  GUID orphelins, ainsi que treize caches de checkpoints anciens. `Resource Types` et `data.vmcx`
  sont conservés.
- `cleanup-hyperv-orphan-cache-admin.ps1` sauvegarde uniquement ces entrées, redémarre VMMS,
  exige zéro erreur et les deux VM Marvin présentes, puis restaure automatiquement en cas d'écart.
  Le premier lancement n'a produit aucun rapport et n'a pas arrêté VMMS; aucune mutation n'a eu lieu.
  Un rapport d'échec déterministe est désormais écrit lors du prochain lancement.
- Deux lancements non élevés via `Start-Process -Verb RunAs` n'ont pas atteint le script et n'ont
  créé ni sauvegarde ni rapport. Le lanceur détecte désormais un token administrateur et exécute
  directement le nettoyage dans ce même processus; le batch doit être lancé par clic droit
  **Exécuter en tant qu'administrateur**. Le trap écrit sur stderr sans récursion `Write-Error`.
- Nettoyage finalement réussi à `18:51:56` : 12 caches VM et 13 caches checkpoints retirés
  après sauvegarde dans `data/hyperv-store-backup/20260717-185149`. Validation post-VMMS :
  deux VM Marvin, zéro erreur `Get-VM`, rollback non déclenché, Wi-Fi `Up` avant et après.
- Le message final `$LASTEXITCODE` était secondaire au lanceur et postérieur au succès. Le
  lanceur retourne désormais explicitement `0` après une exécution PowerShell sans exception.

### Validation logicielle

- `test_vm_lab.py` couvre empreinte correcte, refus sans confirmation, invalidation après
  modification, capacité disque et commutateur Hyper-V.
- Validation consolidée : 31/31 étapes, 100 fichiers Python compilés, 340 outils, 338 routes,
  39 pages, aucune erreur ESLint et 37 avertissements préexistants.
- Backend redémarré en `2.240.0`; les deux profils sont vérifiés et les deux VM sont observées
  par nom exact via `/api/vm-lab/status`.
- Smoke HTTP live : 28/28 contrats, y compris API et proxy VM Lab.
- Parcours Playwright réel : VM Lab, deux ISO vérifiées et `Default Switch` visibles; capture
  `artifacts/tests/code-vm-lab-v2240.png` vérifiée.

## 2026-07-17 — v2.241.0 — installations VM autonomes et validation Windows native

### Demande

Installer Debian puis Windows 11, rendre tout le parcours exécutable par Marvin lui-même,
gérer le dialogue d'affichage VMConnect et continuer la certification de code Windows/Linux.

### Debian 13.6

- Média netinst remasterisé avec preseed et démarrage automatique, construit dans un conteneur
  Debian épinglé sans accès réseau pendant la phase de génération.
- Installation réelle réussie dans `Marvin-Debian13-TestForge`; compte `marvin`, root verrouillé,
  aucun mot de passe invité, authentification Ed25519 dont la clé privée reste sous DPAPI.
- Python 3.13.5, ShellCheck, SSH et services Hyper-V observés; arrêt propre, ISO détachée et
  checkpoint `Marvin-Clean` créé.

### Windows 11 Pro

- ISO Windows 11 25H2 française inspectée : index 6 = Windows 11 Professionnel. Autounattend
  contient un secret aléatoire transitoire protégé par ACL et DPAPI, jamais journalisé.
- L'ISO 2026 a nécessité Secure Boot désactivé uniquement pour Windows Setup; le système installé
  a ensuite démarré avec Secure Boot `On` et le modèle `MicrosoftWindows` avant certification.
- Cause AutoLogon : `Restart-VM -Force` perdait des écritures de registre non vidées. Correction
  par redémarrage demandé dans l'invité et compteur AutoLogon temporaire explicite.
- Cause WinGet initiale : l'alias App Installer est absent du `PATH` des tâches planifiées.
  Résolution de `winget.exe` depuis `Microsoft.DesktopAppInstaller`, tâche interactive reprenable,
  journal par paquet et trois retries bornés avec actualisation de source.
- Python 3.13.14, Node 24.18.0, Git 2.55.0.windows.3, Go 1.26.5 et .NET SDK 10.0.302 installés
  et exécutés. AutoLogon supprimé, mot de passe registre absent, compte `marvin` rétrogradé en
  utilisateur standard et ajouté à `Remote Management Users`.
- Arrêt invité corrigé : le module Hyper-V hôte ne supporte pas `Stop-VM -Shutdown`; le flux
  utilise `shutdown.exe` via PowerShell Direct puis attend l'état `Off`.
- Le vTPM interdit de réécrire l'identifiant du modèle Secure Boot après initialisation; Marvin
  conserve le modèle existant et ne change que `EnableSecureBoot`.

### Autonomie Marvin

- `vm_lab_jobs.py` fournit un job persistant mono-installation avec confirmation, contrôle ISO,
  capacité, PID, journal, réconciliation après redémarrage et résultat déterministe.
- Outil agentique `vm_lab_install`, API `GET/POST /api/vm-lab/install` et boutons de Code Workspace.
  Seule la VM du profil explicitement confirmé est recréée.
- `run-vm-lab-install.ps1` est l'orchestrateur portable; `install-windows-vm-lab.ps1` utilise
  désormais le provisionneur validé au lieu de l'ancien WinGet direct défaillant.
- Le dialogue VMConnect a été fermé réellement. Marvin possède déjà `pc_gui_read` et
  `pc_gui_click`; le prompt impose lecture récente, `automation_id` observé (`m_ConnectButton`)
  et vérification de disparition, sans coordonnées figées.
- Procédure portable et rollback documentés dans `VM-LAB.md`.

### Validations réelles

- Les deux VM sont arrêtées, mémoire assignée nulle et checkpoint `Marvin-Clean` présent.
- Smoke `smoke_hyperv_runner_live.py` : Windows 11 build 26200, compte non administrateur,
  compilation Python et unittest réussis, réseau VM déconnecté, checkpoint restauré avant/après,
  `production_ready=true`, durée 41,875 secondes.
- Parseurs PowerShell des scripts concernés : réussis.
- Compilation Python ciblée : réussie.
- `test_vm_unattended.py`, `test_vm_lab.py`, `test_vm_lab_jobs.py` et
  `test_hyperv_test_runner.py` : réussis.
- ESLint ciblé `app/code/page.jsx` : aucune erreur ni avertissement.
- Architecture intermédiaire : Marvin 2.240.0 avant bump, 341 outils, 340 routes, 39 pages et
  61 outils encadrés. Le contrôle final 2.241.0 est exécuté après mise à jour documentaire.
- Validation finale `scripts/check_marvin.py --quick` : 31/31 étapes réussies sous Marvin
  2.241.0, 341 outils, 340 routes, 39 pages, 102 fichiers Python compilés et zéro erreur ESLint
  (37 avertissements préexistants).
- Build de production Next.js 16.2.6 avec Turbopack réussi. Parcours Chrome Playwright réel sur
  `http://localhost:3000/code` : onglet Bibliothèque hydraté, VM Lab Hyper-V visible, deux ISO
  vérifiées et deux commandes d'installation présentes; capture
  `artifacts/tests/code-vm-lab-v2241.png`.
- Contrôle UI Automation après action : aucun descendant `m_ConnectButton` ni dialogue
  « Configuration de l'affichage » ne subsiste. Les consoles VMConnect normales restent
  ouvertes sans modifier les VM.
- Contrôle final Hyper-V : les deux VM sont `Off`, mémoire assignée nulle et checkpoint
  `Marvin-Clean` présent; aucun fichier transitoire de secret, `Autounattend.xml` ou seed ISO
  n'est resté dans `data/`.

## 2026-07-17 — v2.242.0 — Code Workspace prompt-first, chat et preuve Debian

### Demande et constat

- L'utilisateur ne pouvait pas cliquer sur les accès rapides Code Forge, Test Forge et
  Knowledge Radar et pensait que Code Workspace était une application séparée.
- La page `/code` exigeait un dépôt Git déjà existant, ce qui empêchait une demande saisie
  directement comme dans Codex ou Claude Code.
- La conversation « Script Zabbix Debian 13 » contient un reçu réel `ai_test_forge` en échec,
  alors que la réponse suivante annonçait 72/73 puis 74/74 tests réussis. Marvin a ensuite
  prétendu ne pas pouvoir tester depuis Windows et a demandé des identifiants SSH, malgré le
  runner Debian 13 Docker et le VM Lab disponibles.

### Décisions et modifications

- `coding_scratch.py` crée, après confirmation, un dépôt Git propre et portable sous
  `%LOCALAPPDATA%\Marvin\workspaces\code\requests` quand aucun dépôt n'est fourni.
- `coding_service.py` devient le contrat partagé par l'API, l'interface et le chat. Il infère
  Linux pour Debian/Bash/Zabbix et Windows pour PowerShell/WPF, puis crée mission, worktree et
  job Auto sur la boucle FastAPI courante.
- `/code` accepte un prompt direct, propose la cible Auto/Linux/Windows/mixte et transforme
  les trois anciens libellés en boutons. L'accès Test Forge ouvre un onglet dédié exposant
  Docker, l'image Debian épinglée, l'intégration Internet et le runner Windows.
- Les outils chat `code_workspace_start`, `code_workspace_status` et
  `code_workspace_control` couvrent création, lecture, reprise et annulation. Les mutations
  restent soumises à confirmation et sont bloquées dans le profil sécurisé.
- Le routeur agentique force ces outils sur une demande explicite Code Workspace/Coding
  Mission. Un script/code mentionné dans le tour précédent est repris comme contexte.
- `test_forge.requires_online_integration` détecte les installeurs Linux. `apt`, `dnf`,
  `yum`, `apk`, `pip install`, `npm install`, `dpkg` ou `systemctl` imposent désormais une
  intégration Debian en ligne; l'absence de harness refuse `production_ready`.
- Un reçu négatif `ai_test_forge` ou `ai_code_forge` bloque les tokens narratifs ultérieurs
  et produit une réponse déterministe « Validation non obtenue » jusqu'à une nouvelle preuve
  explicite de succès.

### Validations réelles

- Compilation Python ciblée : réussie.
- `test_coding_service.py` : dépôt Git temporaire réel, cible Debian, registres d'outils et
  exécution des commandes chat sur la boucle asyncio, réussis.
- `test_test_forge.py` et `test_intent_guards.py` : réussis.
- Smoke connecté `test_test_forge_online.py` : conteneur Debian 13 jetable, `apt-get update`,
  installation réelle de Python, exécution `unittest` et marqueurs de fin, `production_ready`.
- ESLint ciblé : zéro erreur. Build Next.js 16.2.6 Turbopack : réussi.
- Architecture avant bump : 344 registres/spécifications d'outils cohérents, 340 routes,
  39 pages et 63 outils encadrés.
- Parcours navigateur réel sur `/code` : les trois accès rapides sont des boutons; Test Forge
  affiche Docker disponible, Debian 13 et runner Hyper-V prêt; Knowledge Radar s'ouvre; un
  prompt direct sans dépôt active « Démarrer dans Code Workspace ».
- Validation globale `scripts/check_marvin.py --quick` : 32/32 étapes réussies sous Marvin
  2.242.0, 344 outils, 340 routes, 39 pages et 104 fichiers Python compilés. ESLint conserve
  37 avertissements préexistants mais aucune erreur. Build Next.js 16.2.6 Turbopack réussi.
- Après redémarrage : `/api/health` retourne `status=ok`, version 2.242.0, 344/344 outils,
  Ollama connecté; `http://127.0.0.1:3000/code` retourne HTTP 200.

### Rollback

- Revenir aux fichiers listés dans cette entrée. Les dépôts scratch peuvent être supprimés
  individuellement uniquement après vérification qu'aucune Coding Mission ne les référence.
  Aucun dépôt scratch ni mission utilisateur n'a été créé pendant le test navigateur.

## 2026-07-18 — v2.243.0 — Cloud strict, conversations et Test Forge Debian natif

### Demande et diagnostic

- L'utilisateur a signalé qu'en mode Ultra débridé Marvin était passé sur un modèle local.
  Le contrat attendu est au contraire « tout cloud »; les modèles locaux restent réservés aux
  profils de confidentialité, sauf choix explicite hors Ultra.
- La conversation récente « Script Zabbix Debian 13 » a été relue. La mission Code Forge a
  bien utilisé des familles Ollama Cloud, mais le chat principal pouvait encore revenir au
  local lors d'une escalade de compétence, d'un OCR, d'une analyse d'image ou d'un repli interne.
- La même conversation a répété `code_workspace_status` plus de dix fois en quelques secondes
  et a décrit une progression non prouvée. Le reçu final réel était un échec : le conteneur
  Debian ne possède pas d'init `systemd`, et la suite Bats n'était pas exploitable.
- La VM `Marvin-Debian13-TestForge` et son checkpoint `Marvin-Clean` existaient bien. Ils
  n'étaient simplement pas reliés à Test Forge pour les parcours Linux natifs.

### Décisions et modifications

- `cloud_routing.py` formalise un mode cloud-only. En Ultra, tout modèle demandé — y compris
  un modèle local manuel ou vision — est résolu vers un modèle Ollama Cloud installé. Si aucun
  cloud n'est disponible, l'appel échoue explicitement; aucun repli local silencieux n'existe.
- `agent.py` conserve le cloud lors de l'escalade de compétence et ignore les préférences
  Cortex local/hybride en Ultra. Les répétitions identiques de statut dans un même tour sont
  bloquées. `tools.py` applique le même contrat à OCR, vision et aux générations internes.
- Le preset de confidentialité passe par un endpoint transactionnel unique. Hyper local reste
  prioritaire sur Ultra en cas d'état incohérent, et le garde-fou des commandes catastrophiques
  demeure actif dans tous les profils.
- `test_forge.py` détecte les appels `systemctl`, `service`, `loginctl`, `hostnamectl` et
  `timedatectl`. Les contrôles Docker restent le premier filtre; un parcours natif est ensuite
  envoyé à `linux_test_runner.py`.
- Le runner restaure `Marvin-Clean`, démarre Debian avec le réseau invité, copie uniquement le
  bundle par SSH, exécute le harnais privilégié borné, puis restaure la base saine. Un succès
  crée `Marvin-Result-<run_id>` avant la restauration : Code Workspace peut ouvrir ce résultat
  pour un contrôle manuel, puis restaurer la base et supprimer le snapshot. Une session manuelle
  bloque toute nouvelle certification.
- Le compte Debian reste sans sudo général. Le preseed autorise seulement l'extinction et
  `/usr/local/sbin/marvin-test-forge-runner`, avec identifiant de passage validé. La clé privée
  SSH reste sous DPAPI et aucun secret hôte n'est transmis dans le JSON PowerShell.
- Code Forge réutilise une suite Bats livrée lorsque le modèle QA échoue. Une erreur
  d'indentation détectée pendant les régressions, qui empêchait Test Forge de s'exécuter lorsque
  les tests générés étaient valides, a été corrigée avant livraison.

### Validations observées à ce stade

- Compilation Python ciblée : réussie.
- `test_cloud_only_routing.py` : chat, vision, repli interne et presets cloud-only réussis;
  Hyper local prioritaire vérifié.
- `test_linux_test_runner.py` : restauration avant/après, preuve native, résultat temporaire,
  ouverture manuelle et retour propre réussis sans mutation réelle d'Hyper-V.
- `test_test_forge.py`, `test_vm_unattended.py`, `test_code_forge.py` : réussis.
- ESLint ciblé Code Workspace/Réglages : zéro erreur; un avertissement React préexistant dans
  Réglages demeure sans rapport avec cette évolution.
- Reprovisionnement réel terminé par le job `vm-lab-6c06dba71d73`; l'ISO unattended a été
  relue et comparée par `xorriso`. Debian 13, Python 3.13.5, ShellCheck, Bats 1.11.1, SSH et le
  harnais natif version 1 ont été observés avant la création de `Marvin-Clean`.
- Smoke direct réel : unité transitoire `systemd-run`, service SSH actif, Bats 1/1,
  `production_ready=true`, checkpoint restauré avant/après. Le snapshot résultat a été ouvert,
  la VM observée `Running`, puis « restore » l'a ramenée `Off` et a supprimé le snapshot.
- Smoke Test Forge complet réel : Docker syntaxe/ShellCheck/Bats, routage automatique motivé
  `native_linux_runtime`, exécution VM native et cinq étapes réussies; nettoyage final réussi.
- Validation globale finale `scripts/check_marvin.py --quick` : 34/34 étapes réussies, incluant
  les contrats Ultra cloud-only et runner Debian natif. Architecture : Marvin 2.243.0,
  344 outils, 343 routes, 39 pages. Build Next.js 16.2.6 Turbopack réussi en 18,6 secondes.
- Backend redémarré sans relancer Ollama ni réinstaller de dépendance. `/api/health` expose
  2.243.0 et 344/344 outils; `/api/coding/overview` expose Debian `ready=true` et harnais natif
  présent. État Hyper-V final : VM `Off`, unique checkpoint `Marvin-Clean`.

### Rollback

- Restaurer les fichiers de cette entrée et reprovisionner la VM Debian avec le preseed de la
  version précédente. La restauration `Marvin-Clean` et la suppression des checkpoints
  `Marvin-Result-*` ramènent la VM à son état de référence; aucune donnée utilisateur n'y réside.

## 2026-07-18 — v2.244.0 — Conversation human-first et détails progressifs

### Demande et diagnostic

- L'utilisateur a signalé que les dernières conversations étaient trop denses pour être lues
  humainement. L'historique récent « Script Zabbix Debian 13 » a été mesuré, sans lire ni
  reproduire de secret : une réponse atteignait environ 38 800 caractères, un résultat web
  environ 14 500 caractères et les appels d'outils étaient persistés comme messages séparés.
- Les interrogations répétées `code_workspace_status` affichaient plusieurs formulations du
  même avancement. La réponse finale de 2 468 caractères était pertinente, mais ses tableaux
  et sections occupaient presque tout l'écran avant l'action utile.

### Décisions et modifications

- `lib/chatPresentation.mjs` construit une vue de lecture sans modifier les messages stockés :
  les appels techniques consécutifs sont regroupés et les sondages de statut successifs ne
  conservent visuellement que le texte le plus récent, tout en gardant chaque preuve d'outil.
- `MessageBubble.jsx` replie toute activité terminée en une ligne. Les erreurs montrent un
  résumé court; les confirmations critiques restent visibles. Chaque carte propose ensuite le
  détail technique complet, qui continue d'utiliser les rendus spécialisés et `PrettyResult`.
- Les réponses longues sont limitées à 460 px sur bureau et 380 px sur mobile, avec dégradé et
  bouton explicite d'expansion. Aucun contenu, source, revue, résultat ou JSON n'est supprimé.
- `MessageBubble.module.css` ajoute les contrôles accessibles, les états d'erreur et le repli
  responsive. `ChatContainer.jsx` applique uniquement la projection de lecture aux messages.

### Validations observées

- `scripts/test_chat_presentation.mjs` : 9 assertions réussies, dont non-mutation, frontières de
  regroupement, statut le plus récent et conservation de toutes les preuves.
- ESLint ciblé : zéro erreur; six avertissements historiques (`img` et dépendance de hook) sans
  rapport avec cette évolution.
- Build Next.js 16.2.6 Turbopack : réussi, 39 pages générées.
- Inspection visuelle réelle de la dernière conversation dans Chrome : l'activité finale est
  affichée sur une ligne, la réponse finale sur une hauteur bornée et les deux contrôles de
  dépliage fonctionnent. Dix-sept groupes d'activité et six réponses longues étaient présents;
  l'ouverture d'une activité a révélé son contrôle de détail technique sans erreur de page.
- Le frontend Turbopack a été redémarré après détection d'un canal HMR invalide. Le backend a
  ensuite été redémarré pour exposer la version 2.244.0; Ollama n'a pas été redémarré.

### Rollback

- Retirer la projection `groupConversationMessages`, restaurer le rendu direct des résultats
  dans `ToolCallInline` et supprimer les styles v2.244. Les conversations persistées ne demandent
  aucune migration : cette évolution est exclusivement une projection d'interface.

## 2026-07-18 — v2.245.0 — Vues Lecture, Technique et Audit

### Demande et conception

- L'utilisateur a validé les trois prolongements proposés après la consolidation human-first :
  une vue Lecture, une vue Technique et une vue Audit exportable.
- Deux options ont été comparées. Un sélecteur placé dans l'en-tête principal aurait nécessité
  de remonter l'état et les messages dans `app/page.js`. Une barre appartenant à
  `ChatContainer` garde la responsabilité au niveau où vivent réellement les messages, évite
  le couplage avec la sélection des modèles et reste disponible pour une nouvelle conversation.
- Le choix est global au navigateur grâce à `localStorage`, mais aucune préférence d'interface
  n'est écrite dans la base ou synchronisée hors de la machine.

### Modifications

- `ConversationViewToolbar.jsx` et son module CSS fournissent trois onglets accessibles :
  Lecture replie les détails; Technique ouvre activités, résultats et réponses longues; Audit
  restitue les messages originaux sans regroupement.
- `ChatContainer.jsx` mémorise le mode, sélectionne la projection correspondante et produit les
  téléchargements locaux. Sans message, les exports restent désactivés.
- `MessageBubble.jsx` synchronise le repli des activités, des réponses longues et des résultats
  avec le mode courant. Une confirmation sensible reste visible quel que soit le mode.
- `chatPresentation.mjs` produit un contrat d'audit versionné et un Markdown chronologique. Les
  clés sensibles connues sont masquées récursivement avant la sérialisation JSON ou Markdown;
  les références circulaires ne peuvent pas faire échouer l'export.

### Validations observées

- Régressions de présentation : 14 assertions réussies, incluant regroupement, non-mutation,
  masquage imbriqué des secrets et absence de réintroduction dans le Markdown.
- ESLint ciblé : zéro erreur; six avertissements historiques sans rapport avec cette évolution.
- Validation navigateur sur la conversation réelle Zabbix : Lecture replie les détails;
  Technique ouvre 41 résultats techniques et toutes les réponses longues; Audit expose la
  chronologie originale et les boutons Markdown/JSON. Le mode Audit reste sélectionné après
  rechargement et les exports deviennent inactifs quand aucune conversation n'est ouverte.
- Test responsive à 390 × 844 : les trois modes et les deux exports restent accessibles; les
  descriptions secondaires sont masquées pour préserver l'espace de conversation.
- Validation globale `scripts/check_marvin.py --quick` : 34/34 étapes réussies. Architecture :
  Marvin 2.245.0, 344 outils, 343 routes et 39 pages.
- Build Next.js 16.2.6 Turbopack : réussi. Après redémarrage, le frontend répond HTTP 200 et
  `/api/health` expose 2.245.0, Ollama connecté et 344/344 outils.

### Rollback

- Retirer `ConversationViewToolbar`, revenir à `groupConversationMessages(messages)` sans
  condition et supprimer les fonctions d'audit. Les conversations et préférences backend ne
  nécessitent aucune migration ni restauration.

## 2026-07-18 — v2.246.0 — Historiques restaurés et protection du cache Turbopack

### Incident et cause racine

- Après une nouvelle conversation « Simple salutation amicale », l'utilisateur a quitté la vue
  puis est revenu : la conversation était listée mais son contenu semblait vide.
- L'API FastAPI contenait toujours les deux messages, avec identifiants et parts intacts. Aucun
  enregistrement n'avait été perdu ou écrasé.
- Le proxy Next `/api/conversations/{id}` répondait 404. Le manifeste de développement ne
  contenait plus aucune route dynamique `[id]` ou `[...path]`, alors que le manifeste de build
  les contenait. La première cause est un `next build` exécuté pendant que `next dev` utilisait
  le même dossier `.next`; le canal HMR invalide observé précédemment était le premier symptôme.

### Correction

- Le cache `.next/dev` généré a été nettoyé après arrêt du frontend. Au redémarrage, la route
  dynamique a été recompilée et les deux messages sont réapparus immédiatement.
- `start_next_dev.mjs` refuse une seconde instance puis retire uniquement le graphe serveur et
  les manifestes générés avant de relancer `next dev -H 0.0.0.0` avec Turbopack.
- `build_next_safe.mjs` teste le verrou exclusif `.next/dev/lock`; un build concurrent s'arrête
  avant toute écriture et explique la procédure correcte.
- `app/page.js` dispose en plus d'un repli direct vers FastAPI pour les opérations dynamiques de
  conversation et projet lorsque le proxy Next est absent ou retourne 404. Les autres erreurs
  ne sont pas rejouées afin d'éviter une mutation en double. Un toast remplace l'échec silencieux.
- Le smoke test chat classe maintenant comme régression toute conversation qui retombe sur
  `.empty-state` après sa sélection.

### Validations observées

- Frontend proxy après nettoyage : HTTP 200, deux messages relus pour la conversation signalée.
- Validation navigateur : `salut` et la réponse Marvin sont de nouveau visibles; l'état vide a
  disparu.
- Smoke chat réel : cinq conversations récentes sur cinq réussies, dont la salutation et Zabbix.
- Garde de build testée avec frontend actif : arrêt volontaire code 2 avant toute écriture.
- Régressions de présentation : 14 assertions réussies. Validation globale
  `scripts/check_marvin.py --quick` : 34/34 étapes réussies, sans erreur ESLint.
- Cycle final reproductible : arrêt du port 3000, build Next.js 16.2.6 Turbopack réussi, puis
  redémarrage par `npm run dev`. Le manifeste inclut `/api/conversations/[id]`.
- Après ce cycle complet, le proxy frontend restitue encore les deux rôles `user,assistant`, le
  smoke chat repasse cinq conversations sur cinq et les services répondent HTTP 200.
- Le backend redémarré expose la version 2.246.0, l'état `ok` et Ollama connecté.

### Rollback

- Restaurer les scripts npm `dev` et `build`, retirer le repli FastAPI et l'assertion `.empty-state`.
  Les données n'ont aucune migration à annuler; `.next` reste un artefact régénérable.

## 2026-07-18 — v2.247.0 — Continuité du chat et contrat Code Workspace vers Test Forge

### Incident et preuves

- En revenant au Chat pendant une réponse, seule la partie déjà persistée réapparaissait. Le
  provider global conservait bien le flux SSE, mais `ChatPage` repartait avec une conversation
  nulle et `ChatContainer` remplaçait les messages vivants lors de son remontage.
- La dernière conversation Zabbix contenait 57 messages. Plusieurs messages techniques vides
  correspondaient à des reçus d'outils; le dernier échange s'arrêtait après un `file_read` vers
  un chemin de worktree inexistant.
- Le livrable refusé existait dans le snapshot durable (`main.sh`, `test.sh`) mais n'était, à
  juste titre, pas appliqué au worktree. Le chat n'avait pas accès à son contenu via
  `code_workspace_status` et tentait donc de deviner des chemins.
- Docker 29.6.1, la VM Debian et la VM Windows étaient installés. Le runner Debian échouait
  toutefois sur le transfert ambigu `input_path\.` puis les harness générés pouvaient coder en
  dur `/workspace` ou `/work/src`, chemins incompatibles entre Docker et la VM native.

### Correction

- `chatNavigation.mjs`, `app/page.js` et `ChatContainer.jsx` reprennent la sélection vivante,
  empêchent un changement de conversation pendant le flux, préservent les messages en cours et
  conservent le brouillon dans `sessionStorage`.
- `coding_service.status` expose des aperçus bornés des fichiers du dernier snapshot et une
  détection mise en cache de Docker, Debian Hyper-V et Windows Hyper-V. Le contrat d'outil et le
  système agent imposent la lecture de ces données au lieu d'un `file_read` inventé.
- `linux_test_runner.py` crée explicitement la racine distante, transfère chaque fichier, valide
  le triplet requis et verrouille l'unique VM contre deux exécutions concurrentes.
- Test Forge refuse les harness sans marqueur ou utilisant un chemin absolu propre à un runner.
  Les prompts Code Forge imposent désormais les chemins relatifs depuis le répertoire courant.

### Validations observées

- Navigation chat : 8 assertions déterministes réussies; ESLint ciblé sans erreur.
- Navigateur réel : brouillon conservé après aller-retour `/code`; pendant un vrai flux, le lien
  Chat affiche `Marvin réfléchit…`, puis le retour conserve le prompt, la réponse et supprime
  l'état vide. La réponse finale est persistée côté backend.
- Runner Debian réel : `production_ready=true`, Bats 1/1, marqueurs intégration et fin présents,
  checkpoint restauré avant et après, réseau hôte non modifié, durée 24,2 secondes.
- Docker réel : bundle Python multi-fichiers valide accepté, module auxiliaire invalide refusé;
  intégration Debian avec Internet et installation de dépendances réussie.
- Tests Coding Service et Linux Runner réussis sans mutation Hyper-V dans leurs régressions.
- Contrôles globaux : présentation 14/14, validation rapide 34/34 et build Next.js 16.2.6
  Turbopack réussi. Après redémarrage, frontend HTTP 200, backend 2.247.0, Ollama connecté et
  344/344 outils chargés.
- Smoke chat après redémarrage : cinq conversations récentes sur cinq relues avec leur contenu.
  L'API `code_workspace_status` restitue `main.sh` et `test.sh` depuis le snapshot de mission;
  Docker 29.6.1 et les runners Debian/Windows sont détectés prêts. La vue Test Forge affiche
  ces trois capacités comme disponibles/prêtes.

### Rollback

- Retirer les helpers de navigation et revenir à l'hydratation directe des messages; retirer les
  aperçus de snapshot et restaurer l'ancien transfert SCP. Aucun schéma ni donnée utilisateur
  n'a été migré. Le rollback du transfert réintroduirait le défaut de racine distante et n'est
  donc pas recommandé.

## 2026-07-18 — v2.248.0 — Marvin Engineering Runtime

### Demande et décision

- L'utilisateur demande que Marvin maîtrise réellement tous ses outils, suive Code Workspace et
  corrige les résultats jusqu'à obtenir un code livrable.
- Le renforcement des prompts a été écarté comme solution principale : le contrôle est déplacé
  dans un runtime déterministe partagé par le Chat, les outils et Coding Missions.

### Implémentation

- `engineering_runtime.py` ajoute un contrat `_contract` non destructif pour les résultats
  d'outils, la classification des pannes, la Definition of Done et le Delivery Pack expurgé.
- `coding_mission.py` expose un journal chronologique à curseur, des événements métier publics et
  un `delivery-pack.json` durable lié aux snapshots.
- `coding_jobs.py` publie chaque étape, conserve les validations réussies, réinjecte la preuve
  exacte dans une passe de réparation ciblée et ne bloque qu'après répétition de la même cause.
- `code_forge.py` diffère l'acceptation finale lorsqu'Auto le pilote. Seul le superviseur peut
  accepter après validation de toutes les cibles et de la Definition of Done.
- `/api/coding/projects/{id}/events/stream` diffuse le journal en SSE reprenable. Le proxy Next
  transmet le flux sans le mettre en mémoire.
- Le Chat affiche une carte Coding Mission actualisée en direct. Code Workspace consomme le même
  flux, ouvre directement la mission demandée et affiche Definition of Done et Delivery Pack.

### Validations observées

- `test_engineering_runtime.py` : contrats, classification, DoD Linux/Windows et manifestes.
- `test_coding_mission.py` : snapshots, reprise, expurgation et concurrence.
- `test_coding_jobs.py` : acceptation, Delivery Pack, événements, annulation, reprise et réparation
  ciblée après un premier refus.
- `test_chat_navigation.mjs` : huit assertions réussies.
- Compilation Python des modules modifiés réussie; ESLint ciblé sans erreur.
- Validation globale `npm run check:quick` : 34/34 étapes, Marvin 2.248.0, 344 outils,
  344 routes et zéro erreur ESLint. Build Next.js 16.2.6 Turbopack réussi.
- Après redémarrage : frontend HTTP 200, backend `ok` 2.248.0 et Ollama connecté. Le proxy SSE
  réel transmet les événements `mission`, les curseurs `id` et l'événement `terminal`.
- Validation navigateur : l'URL `/code?mission=...` ouvre la bonne mission et son superviseur;
  la conversation Zabbix affiche les cartes Coding Mission, leurs états persistés, le suivi direct
  et le bouton d'ouverture dans Code Workspace, sans état vide ni erreur API.

### Rollback

- Retirer l'enrichissement `_contract`, la route SSE et les cartes de suivi; restaurer le polling
  Code Workspace. Les snapshots et `delivery-pack.json` sont additifs et peuvent rester sur disque.

### Validation live complémentaire et corrections issues de l'exécution

- Mission réelle `eff0b73ce5294172b3bd0469d254b037` lancée depuis le superviseur Auto pour
  produire une bibliothèque Python 3.12 multi-fichiers `slugify_safe` sans dépendance externe.
- Les premières passes ont révélé quatre incohérences de runtime qui n'étaient pas visibles
  dans les tests simulés : exigence historique de `main.py` pour une bibliothèque, guillemets
  échappés dans les métadonnées `file=`, détection en ligne déclenchée par la phrase
  négative « aucune dépendance » et non-exécution de la suite contenue dans le bundle.
- `deliverable_bundle.py` reconnaît maintenant un paquet Python `pyproject.toml` +
  `src/<package>/__init__.py`; les chemins nommés échappés sont normalisés sans relâcher les
  protections contre la traversée de chemin.
- `code_forge.py` conserve déterministement le chemin primaire et l'ensemble des fichiers lors
  des réparations. Une sortie cloud qui remplace une bibliothèque par `main.py` ou omet un fichier
  demandé est refusée. La détection d'installation en ligne tient compte des négations.
- `test_forge.py` ne crée plus de `main.py` synthétique pour un layout Python `src/`; il rend
  `/workspace/src` importable et exécute la suite `unittest` livrée. Un passage Docker réel a
  d'abord exposé un défaut Unicode (`U+2028/U+2029`), puis la réparation suivante l'a corrigé.
- Résultat final observé à la tentative 12 : mission `completed`, 11/11 tests Docker hors
  ligne, compilation réussie, Production Contract réussi, API publique typée 1/1, SBOM
  CycloneDX 1.6, aucun constat critique ou élevé, Definition of Done réussie et Delivery Pack
  persistant avec trois fichiers et leurs SHA-256.
- Un essai supplémentaire sur l'hôte Windows a trouvé un test non portable qui compare la casse
  de `SystemRoot` alors que cet environnement expose `SYSTEMROOT`. La cible certifiée de cette
  mission est Linux; ce résultat Windows n'est donc pas présenté comme une certification native.

## 2026-07-18 — v2.250.0 — Reprise visible, voix exclusive et avatar de bureau

### Demande et constats

- L'utilisateur demande que le chat reste la source de vérité d'une Coding Mission, affiche les
  corrections et reprenne après navigation ou incident sans perdre le travail.
- La mission Zabbix Debian 13 existante devait continuer sous le même `mission_id` et être validée
  réellement dans la VM Hyper-V, pas seulement par analyse statique ou Docker.
- Deux défauts audio étaient reproductibles lors de lectures rapprochées : une ancienne boucle
  pouvait consommer la nouvelle file et des fragments d'un ancien flux pouvaient être ajoutés après
  le début de la réponse suivante.
- L'utilisateur demande un avatar de Bureau permettant de parler à Marvin et de démarrer ou arrêter
  l'application sans ouvrir d'abord l'interface complète.

### Implémentation

- `CodingMissionTracker.jsx` consomme le journal SSE durable avec polling de secours et affiche une
  seule carte directe pour la dernière mission de la conversation : phase, tentative, progression,
  corrections, événements récents, Definition of Done et Delivery Pack.
- `ChatContext.jsx` et `useVoice.js` utilisent un numéro de génération exclusif. Une nouvelle réponse,
  une lecture manuelle ou un arrêt invalide immédiatement audio, préchargements et fragments anciens;
  la promesse de lecture attend la fin effective de la file.
- `/avatar` et `desktop-avatar/` ajoutent un renderer Electron 43.1.1 sandboxé, sans Node.js, avec IPC
  minimal, navigation fermée, permission limitée au microphone local et profil isolé dans
  `%LOCALAPPDATA%\Marvin\DesktopAvatar`.
- L'avatar devient une fenêtre compagnon à deux formats : conversation 520 x 680 par défaut et
  compact 390 x 470. Il conserve dix messages, une saisie multiligne, la mission Code active,
  un raccourci global `Ctrl+Maj+Espace`, la position d'écran et un déplacement natif borné. La
  boucle Möbius tourne en perspective 3D tout en gardant le regard robotique asymétrique.
- Le bouton `Ouvrir Marvin` passe par un IPC local borné, ouvre le navigateur par défaut puis
  réduit l'avatar afin que la fenêtre principale ne reste pas cachée derrière `alwaysOnTop`.
- `/api/avatar/status|activate` et le robot dans la barre latérale fournissent un lanceur permanent;
  l'activation d'une instance existante la remet au premier plan sans doublon.
- L'installation écrit `data/install-capabilities.json` avec l'état du socle et des capacités
  optionnelles Docker, Hyper-V, Sandbox et VM; l'absence d'une option ne bloque plus le socle.
- Le raccourci `Marvin Avatar` utilise l'icône issue du SVG officiel Marvin et des chemins calculés
  depuis la racine installée. `INSTALLER-NOUVEAU-PC.bat` prépare le runtime optionnel et crée le
  raccourci sans rendre l'avatar obligatoire pour le socle.
- `stop-marvin.ps1` ne cible que les processus des ports 3000/8005 dont la chaîne de parents appartient
  au projet; Ollama reste actif. L'avatar sait aussi fermer uniquement sa propre fenêtre.
- Code Forge refuse désormais `--allow-remove-essential` et l'activation d'UFW avant les politiques et
  règles d'administration. Ces contrôles empêchent qu'un gate syntaxique accepte un installateur qui
  fragilise Debian ou coupe une session distante.
- Code Forge refuse aussi une vérification des politiques via `ufw status` sans `verbose`, défaut
  reproduit dans la VM Debian; le runner SSH conserve stderr comme preuve sans le confondre avec
  une exception PowerShell lorsque le processus distant retourne son propre code.
- `DESKTOP-AVATAR.md` documente installation, fonctionnement, validation et rollback.

### Validations observées

- `npm run check:quick` : 36/36 étapes, 344 outils, 346 routes, 40 pages et compilation de 107 fichiers
  Python. ESLint : zéro erreur; 37 avertissements historiques non bloquants.
- `npm run build` : Next.js 16.2.6 Turbopack compilé en 21,3 s; route `/avatar` incluse.
- Playwright réel : 40/40 pages sans erreur console; smoke chat : 5/5 conversations, dont Zabbix.
- Avatar : 30 assertions; voix : 10 assertions; test navigateur de deux lectures rapides : une seule
  lecture simultanée au maximum, puis arrêt et nettoyage complets. Electron relancé avec son profil
  isolé, raccourci Bureau présent, ouverture de Chrome confirmée et vue conversation validée.
- `npm audit` : 0 vulnérabilité connue après épinglage d'Electron 43.1.1, DOMPurify 3.4.12 et overrides
  transitoires Babel/js-yaml/PostCSS.
- Suites `test_code_forge.py`, `test_test_forge.py`, `test_coding_jobs.py`,
  `test_engineering_runtime.py` et `check_architecture.py` réussies.
- Mission Zabbix `30e06720235047178855b6736d4f94dc`, job
  `coding-job-c6d52e646c32` : reprise confirmée après redémarrage backend sous le même identifiant et
  depuis le dernier snapshot. Le résultat terminal sera ajouté ci-dessous après la preuve Debian.

### Résultat terminal de la mission Zabbix

- En attente de la fin de Test Forge natif au moment de cette entrée.

### Rollback

- Retirer `AppFrame`, `/avatar`, `desktop-avatar/` et le raccourci pour revenir à l'interface web seule.
  La suppression du raccourci n'affecte aucune conversation ni Ollama.
- Retirer les deux contrôles Bash de `_bash_checks` uniquement si le risque de suppression de paquets
  essentiels ou de coupure firewall est accepté explicitement; ce rollback n'est pas recommandé.

## 2026-07-18 — v2.251.0 — Avatar de bureau : déplacement et redimensionnement natifs

### Demande et constats

- L'utilisateur signale que la fenêtre de l'avatar de bureau (livrée en v2.250) ne peut être ni
  déplacée ni redimensionnée correctement.
- Lecture du code : `desktop-avatar/main.cjs` créait la fenêtre avec `frame: false` et
  réimplémentait le déplacement à la main (`setInterval` de 16 ms sondant
  `screen.getCursorScreenPoint()`, doublé d'un second circuit IPC `marvin:drag-move` déclenché
  par les événements `pointermove` du renderer) — deux mécanismes concurrents pour la même
  action. Aucun redimensionnement n'était implémenté; sur Windows, `frame: false` désactive par
  défaut la bordure de redimensionnement native (confirmé par plusieurs tickets ouverts du dépôt
  Electron). Dans `app/avatar/page.jsx`, la quasi-totalité des éléments interactifs portait
  `data-no-drag="true"`, ne laissant que de fines marges comme zone déplaçable — ce qui expliquait
  la sensation que « la fenêtre ne bouge pas » même quand le mécanisme de sondage fonctionnait.
- Constat notable : `desktop-avatar/offline.css` utilisait déjà, correctement, le pattern natif
  `-webkit-app-region: drag`/`no-drag` — seule la page `/avatar` (utilisée au quotidien une fois
  Marvin démarré) avait le mécanisme buggé, incohérence entre les deux états de la même fenêtre.
- Recherche du pattern recommandé par la documentation Electron (Custom Title Bar) : remplacer
  `frame: false` par `titleBarStyle: 'hidden'` + `titleBarOverlay` restaure le redimensionnement
  natif par bordures/coins et l'ancrage Windows (Aero Snap) tout en gardant une barre de titre
  invisible, avec un déplacement en CSS natif (`app-region`) plutôt qu'un polling manuel.

### Implémentation

- `desktop-avatar/main.cjs` : `frame: false` remplacé par `titleBarStyle: 'hidden'` et
  `titleBarOverlay: { color: '#09090b', symbolColor: '#e4e4e7', height: 32 }` (boutons système
  réduire/fermer stylés au thème sombre) ; ajout de `hasShadow: true`. Suppression complète du
  déplacement par sondage (`dragTimer`, `dragOffset`, `startWindowDrag`/`stopWindowDrag`/
  `moveWindowDrag`) et des canaux IPC `marvin:drag-start`/`drag-move`/`drag-stop`.
  `setWindowMode` (bascule conversation/compact) inchangé et toujours compatible.
- `desktop-avatar/preload.cjs` : retrait de `startDrag`/`moveDrag`/`stopDrag` de la surface IPC
  exposée (code mort).
- `app/avatar/page.jsx` : retrait de `draggingRef`, `beginDrag`, `moveDrag` et de l'effet
  `pointerup`/`pointercancel`/`blur`. Nouvelle bande de titre fixe dimensionnée avec
  `env(titlebar-area-x/y/width/height)` (ne chevauche jamais les boutons système), portant
  `WebkitAppRegion: 'drag'` ; les commandes interactives (bascule compact, ouvrir Marvin) restent
  `WebkitAppRegion: 'no-drag'`. Le reste du contenu (conversation, saisie, boutons d'action) est
  hors de la zone de titre et n'a donc plus besoin d'être marqué `data-no-drag` individuellement.
  Bouton de fermeture personnalisé retiré (redondant avec le bouton fermer natif de l'overlay).
- `desktop-avatar/offline.html`/`offline.css`/`offline.js` alignés sur le même pattern (bande de
  titre `env(titlebar-area-*)`, bouton fermer natif) pour rester cohérents entre l'état arrêté et
  l'état actif de l'avatar.
- `scripts/test_desktop_avatar.mjs` : assertions `marvin:drag-start`/`marvin:drag-move`/
  `data-no-drag="true"` remplacées par des vérifications du nouveau mécanisme
  (`titleBarStyle: 'hidden'`, `titleBarOverlay`, `resizable: true`, absence de `setInterval`,
  présence de `WebkitAppRegion`/`titlebar-area-width`).
- Version bumpée 2.250.0 → 2.251.0 (`package.json`, `package-lock.json`, `backend/app_version.py`,
  `README.md`, `AGENTS.md`).

### Validations

- `npm run check:avatar` (`scripts/test_desktop_avatar.mjs`) : 30 assertions réussies.
- `npx eslint app/avatar/page.jsx desktop-avatar/main.cjs desktop-avatar/preload.cjs
  desktop-avatar/offline.js --quiet` : aucune erreur.
- `backend/.venv/Scripts/python.exe scripts/check_architecture.py` : OK, versions alignées
  (2.251.0), 344 outils, 346 routes, 40 pages.
- Non testé en conditions réelles (fenêtre Electron native sur Windows) dans cette session — les
  outils de prévisualisation disponibles pilotent un navigateur web, pas une fenêtre Electron
  native. À valider par l'utilisateur : lancer `Marvin Avatar` (ou `LANCER-AVATAR-MARVIN.bat`),
  vérifier que la fenêtre se déplace en cliquant-glissant la bande de titre (au-dessus de
  l'avatar) et se redimensionne depuis les bords/coins, et que la position/taille survit à un
  redémarrage de l'avatar.

### Rollback

- `git diff`/`git checkout -- desktop-avatar/ app/avatar/page.jsx scripts/test_desktop_avatar.mjs`
  restaure le mécanisme précédent si un défaut natif imprévu apparaît sur un poste donné.

## 2026-07-18 — v2.252.0 — Avatar de bureau : régression titleBarOverlay corrigée par des poignées de redimensionnement explicites

### Demande et constats

- L'utilisateur confirme après la v2.251 : le déplacement de la fenêtre fonctionne, mais **plus
  aucun bouton de l'avatar ne répond** (bascule compact, ouvrir Marvin, parler, envoyer,
  arrêter Marvin — tous silencieux).
- Cause précise non confirmable depuis cette session (pas d'accès à une fenêtre Electron
  native pour reproduire) : la v2.251 avait remplacé `frame: false` par
  `titleBarStyle: 'hidden'` + `titleBarOverlay` en s'appuyant sur la documentation Electron du
  pattern « Custom Title Bar » (Window Controls Overlay), qui promet un redimensionnement natif
  gratuit. En pratique, sur cette combinaison Electron 43.1.1 / Windows 11, l'activation de
  l'overlay a rendu la totalité de la fenêtre insensible aux clics de l'interface React, alors
  que le déplacement (porté par une bande `-webkit-app-region: drag` distincte) continuait de
  fonctionner. Hypothèse retenue : interférence du hit-test WCO avec les événements pointeur
  de la page, non documentée dans les sources consultées.
- Décision : ne pas s'entêter sur un mécanisme dont le comportement réel diverge de la
  documentation et n'est pas vérifiable depuis cet environnement de travail ; revenir à un
  design entièrement maîtrisé et testable par assertions statiques.

### Implémentation

- `desktop-avatar/main.cjs` : retrait de `titleBarStyle`/`titleBarOverlay`, retour à
  `frame: false` (conservé : `resizable: true`, `hasShadow: true`, `alwaysOnTop: true`).
  Ajout de `startResize(edge)`/`stopResize()` : au `mousedown` sur une poignée, capture la
  position du curseur et les bornes de départ, puis un `setInterval` de 16 ms (même technique
  que l'ancien déplacement — nécessaire car le curseur peut sortir de la zone de contenu
  pendant le geste, ce qu'un simple `mousemove` DOM ne capterait pas) recalcule `x/y/width/height`
  selon le bord (`n`/`s`/`e`/`w`/`ne`/`nw`/`se`/`sw`), borné par `MIN_WIDTH`/`MIN_HEIGHT` (390×470)
  et la zone de travail de l'écran courant (`getDisplayNearestPoint`), puis appelle `setBounds`.
  Nouveaux canaux IPC `marvin:resize-start`/`marvin:resize-stop`, validés par `trustedSender`
  comme le reste de la surface IPC. `stopResize()` appelé aussi dans `before-quit`.
- `desktop-avatar/preload.cjs` : expose `startResize`/`stopResize`.
- `app/avatar/page.jsx` : la bande de titre redevient un élément en flux normal (plus de
  `position: fixed` ni de dépendance à `env(titlebar-area-*)`, qui n'apportait plus rien sans
  overlay natif) portant `WebkitAppRegion: 'drag'`, boutons internes en `no-drag`. Bouton de
  fermeture personnalisé « × » restauré (plus de bouton système sans `titleBarOverlay`).
  8 poignées de redimensionnement (`RESIZE_EDGES`) rendues en `position: fixed` sur les bords et
  coins de la fenêtre, `WebkitAppRegion: 'no-drag'`, curseur adapté (`ns-resize`/`ew-resize`/
  `nwse-resize`/`nesw-resize`), déclenchant `marvinDesktop.startResize(edge)` au `pointerdown`.
  Un effet global écoute `pointerup`/`pointercancel`/`blur` pour appeler `stopResize()`.
- `desktop-avatar/offline.html`/`offline.css`/`offline.js` : même traitement (bouton fermer
  restauré, 8 poignées de redimensionnement ajoutées) pour rester cohérents entre l'état arrêté
  et l'état actif de l'avatar.
- `scripts/test_desktop_avatar.mjs` : assertions `titleBarStyle`/`titleBarOverlay` remplacées
  par la vérification de `frame: false`, `marvin:resize-start`/`marvin:resize-stop` côté
  process principal, et `RESIZE_EDGES`/`startResize` côté page.
- Version 2.251.0 → 2.252.0 partout (source unique + README/AGENTS).

### Validations

- `npm run check:avatar` : 30 assertions réussies.
- `npx eslint app/avatar/page.jsx desktop-avatar/main.cjs desktop-avatar/preload.cjs
  desktop-avatar/offline.js --quiet` : aucune erreur.
- `backend/.venv/Scripts/python.exe scripts/check_architecture.py` : OK, versions alignées
  (2.252.0).
- Non vérifié en conditions réelles dans cette session pour la même raison qu'en v2.251 (pas de
  fenêtre Electron pilotable depuis les outils disponibles). À valider par l'utilisateur :
  déplacement par la bande de titre, redimensionnement depuis les 4 bords et les 4 coins,
  bouton × ferme bien l'avatar, les 6 boutons de commande répondent tous.

### Rollback

- `git diff`/`git checkout -- desktop-avatar/ app/avatar/page.jsx scripts/test_desktop_avatar.mjs`
  restaure l'état d'avant cette entrée (v2.251, mécanisme `titleBarOverlay` cassé) si nécessaire.

## 2026-07-19 — v2.253.0 — Avatar de bureau : régression HMR (127.0.0.1 bloqué) + gestion de conversation

### Demande et constats (partie 1 — régression)

- Après la v2.252, l'utilisateur confirme le déplacement/redimensionnement mais signale que
  **plus aucun bouton ne répond**, seule la saisie de texte semble "fonctionner".
- Consigne explicite : ne pas relancer le socle Marvin (backend + frontend), une mission Code
  Workspace importante tourne. Diagnostic mené sans y toucher : lecture des logs
  (`frontend_runtime.log`, `frontend_runtime_error.log`), puis reproduction dans un onglet du
  navigateur pointé directement sur `http://127.0.0.1:3000/avatar` (page web normale, pas la
  fenêtre Electron) pour isoler le problème sans interagir avec le socle.
- Preuve décisive : `document.body` et tous ses descendants n'avaient **aucune clé
  `__reactFiber*`/`__reactProps*`** — React ne s'était jamais attaché au DOM. Le
  `frontend_runtime_error.log` contenait la cause : *"Blocked cross-origin request to
  Next.js dev resource /_next/webpack-hmr from '127.0.0.1'"*. L'avatar Electron charge
  `http://127.0.0.1:3000` (jamais `localhost`, cf. `AVATAR_URL` dans `main.cjs`) ; le serveur de
  dev Next.js bloque par défaut le websocket HMR pour toute origine hors `localhost`, ce qui
  provoquait un cycle de rechargement complet de la page toutes les ~150 ms (confirmé par la
  répétition de `GET /avatar 200` dans les logs et par les process renderer Electron en
  `SYN_SENT` continu vers le port 3000) — jamais assez de temps pour terminer l'hydratation.
  Le texte tapé restait visible car c'est un `<textarea>` HTML natif sans JS ; les boutons ne
  répondaient jamais car aucun gestionnaire React n'était attaché.

### Correctif (partie 1)

- `next.config.mjs` : ajout de `allowedDevOrigins: ['127.0.0.1']` (solution documentée par
  l'avertissement Next.js lui-même). Nécessite un redémarrage du serveur de dev pour prendre
  effet (les fichiers de config ne sont pas rechargés à chaud).
- Redémarrage **strictement scopé au frontend** : PID identifié sur le port 3000 uniquement
  (`netstat`), vérifié différent du PID backend sur le port 8005, arrêté puis relancé via
  `npm run dev`. Le PID backend (mission en cours) vérifié inchangé avant/après.
- Ancienne fenêtre avatar (coincée dans la boucle) fermée et relancée après coup.
- Validation : plus de boucle dans les logs, `document.body` porte les clés React après
  rechargement, clics et saisie fonctionnels de bout en bout dans l'onglet de test.

### Demande et implémentation (partie 2 — gestion de conversation)

- L'utilisateur observe que l'avatar reste collé à sa conversation d'ouverture : impossible d'en
  démarrer une nouvelle ou de reprendre une conversation existante depuis l'avatar (visible
  seulement en rouvrant la fenêtre principale). Cause : chaque fenêtre (avatar / navigateur)
  monte son propre `ChatProvider` (état mémoire non partagé entre processus Electron distincts).
  Proposé 3 options (nouvelle conversation seule / historique seul / les deux) — l'utilisateur
  choisit les deux, en insistant : **ne modifier que l'avatar**, rien côté Marvin principal.
- `app/avatar/page.jsx` (seul fichier modifié, plus réutilisation en lecture seule de
  `lib/chatNavigation.mjs::canSwitchConversation`, déjà utilisé par `app/page.js` — aucune
  modification de fichier partagé) :
  - Bouton **+** : `setMessages([])` + `setConversationId(null)`, bloqué (notice 3,5 s) si
    `canSwitchConversation` détecte une réponse en cours sur la conversation active.
  - Bouton **🕘** : popover listant les 8 dernières conversations
    (`GET ${BACKEND_URL}/api/conversations?limit=8`, appel direct au backend comme le fait déjà
    le polling `activeJob` existant), fermeture au clic extérieur (`pointerdown` document,
    ref). Clic sur une entrée → `GET ${BACKEND_URL}/api/conversations/{id}` →
    `setMessages(data.messages)` + `setConversationId(id)`, même garde `canSwitchConversation`.
  - Conversation active surlignée dans la liste ; dates formatées `toLocaleString('fr-FR')`.

### Validations

- `npx eslint app/avatar/page.jsx --quiet` : aucune erreur.
- Testé en conditions réelles dans un onglet navigateur (`/avatar`) : liste réelle des 8
  dernières conversations chargée (titres et dates corrects) ; clic sur "Script Zabbix Debian
  13" → historique complet rechargé (markdown, tableaux, tours de conversation) ; clic sur + →
  retour à un état vide propre ("Prêt. Parle-moi ou écris ta demande.").
- Backend (port 8005, mission Code Workspace en cours) non touché à aucun moment — vérifié par
  PID avant/après le redémarrage du frontend.

### Rollback

- `git checkout -- next.config.mjs app/avatar/page.jsx` restaure l'état d'avant cette entrée.
  Le redémarrage frontend n'a pas de rollback applicable (action ponctuelle, pas un changement
  de code).

## 2026-07-19 — v2.254.0 — Avatar de bureau : suppression du plafond à 10 messages

### Demande et constat

- L'utilisateur signale que l'historique affiché dans l'avatar n'est pas complet.
- Cause : `visibleMessages` dans `app/avatar/page.jsx` appliquait `.slice(-10)` — hérité de la
  conception initiale de l'avatar en tant que compagnon léger toujours visible (documenté dans
  `DESKTOP-AVATAR.md` : "relire les dix derniers messages"). Ce choix n'avait plus de sens
  depuis l'ajout de l'historique de conversations (v2.253) : charger une ancienne conversation
  longue (ex. la mission Zabbix, plusieurs dizaines de tours) ne montrait que ses 10 derniers
  messages, les précédents étant retirés du tableau source — impossible de les faire réapparaître
  en scrollant, contrairement à un simple dépassement visuel.

### Implémentation

- `app/avatar/page.jsx` : retrait de `.slice(-10)` sur `visibleMessages`. Le panneau de
  conversation était déjà `overflow: 'auto'` avec auto-scroll vers le bas au montage/changement
  — aucun autre changement nécessaire pour supporter l'historique complet.
- `DESKTOP-AVATAR.md` : description mise à jour ("relire l'historique complet... le panneau
  défile" au lieu de "les dix derniers messages"), mention du bouton nouvelle conversation et
  de l'historique intégré.

### Validations

- `npx eslint app/avatar/page.jsx --quiet` : aucune erreur.
- Testé en conditions réelles (onglet navigateur `/avatar`, backend port 8005 non touché) :
  chargement de la conversation « Script Zabbix Debian 13 » → 34 bulles de messages rendues
  (contre 10 avant le correctif), `scrollHeight` très supérieur à `clientHeight`, `scrollTop`
  positionné en bas (auto-scroll toujours fonctionnel).

### Rollback

- `git checkout -- app/avatar/page.jsx DESKTOP-AVATAR.md` restaure le plafond à 10 messages.

## 2026-07-19 — v2.255.0 — Avatar de bureau : historique complet, warning React, vraie minimisation

### Demande et constats

L'utilisateur signale trois problèmes après la v2.254, avec une capture d'écran de la page
Marvin Forge (état matériel/tests, sans rapport avec l'avatar — probablement jointe par erreur,
ignorée) :
1. « Je ne vois pas toutes les conversations dans l'avatar. »
2. Un avertissement console copié-collé : *"Removing a style property during rerender
   (borderColor) when a conflicting property is set (border) can lead to styling bugs..."*
3. « La touche pour réduire l'avatar vers la barre des tâches ne fonctionne pas bien, il réduit
   juste la taille de l'avatar. »

### Diagnostic et implémentation

1. **Historique incomplet** — `toggleHistory` appelait `GET /api/conversations?limit=8`
   (choix arbitraire initial). Porté à `limit=50`, aligné sur le défaut de
   `db.list_conversations` côté backend et sur le comportement de la page principale (qui
   n'envoie pas de `limit` et récupère donc le défaut serveur). Le popover était déjà
   `overflow: auto` — aucun ajustement de mise en page nécessaire.
2. **Warning React** — `activeSmallButton` (état actif du bouton historique) écrasait
   `borderColor` par-dessus `smallButton` qui définissait `border` en raccourci ('1px solid
   var(--border)'). React ne peut pas retirer proprement une propriété longhand mélangée à un
   raccourci d'un rendu à l'autre (avertissement documenté par React lui-même). Fix :
   `smallButton` réécrit avec `borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--border)'`
   séparés, plus de propriété `border` raccourcie sur cet objet.
3. **Minimisation confuse** — le bouton `−`/`□` (bascule taille conversation/compact,
   `toggleWindowMode`) avait l'apparence d'un contrôle de minimisation standard (glyphe `−`)
   mais ne faisait que rétrécir la fenêtre sans la réduire dans la barre des tâches — aucune
   action de ce type n'existait. Ajout : `desktop-avatar/main.cjs` expose un nouveau canal IPC
   `marvin:minimize` (`windowRef.minimize()`, même mécanisme déjà utilisé par
   `marvin:open-main`), exposé côté `preload.cjs` (`minimize()`), nouveau bouton dédié dans
   l'en-tête de `app/avatar/page.jsx` (glyphe `─`, titre « Réduire dans la barre des tâches »).
   Les icônes de la bascule compact/étendu changées en `⤡`/`⤢` pour ne plus être confondues
   avec un contrôle de fenêtre standard.

### Validations

- `npx eslint app/avatar/page.jsx desktop-avatar/main.cjs desktop-avatar/preload.cjs --quiet` :
  aucune erreur.
- Warning React vérifié résolu en conditions réelles (onglet navigateur `/avatar`) : hook
  temporaire posé sur `console.error` (`window.__capturedErrors`), popover historique ouvert
  puis fermé plusieurs fois après un rechargement propre — 0 appel capturé (contre des
  occurrences confirmées via `read_console_messages` avant le correctif, qui se sont avérées
  provenir d'un état transitoire juste après le hot-reload Turbopack, pas d'un bug persistant).
- Historique : popover ouvert, 50 entrées dénombrées dans le DOM (contre 8 avant), titres et
  dates cohérents avec la base réelle.
- Bouton de minimisation ajouté et présent dans le DOM (`title="Réduire dans la barre des
  tâches"`) ; l'action réelle `windowRef.minimize()` n'est vérifiable que depuis la fenêtre
  Electron (indisponible pour test direct dans cette session — même limite que les sessions
  précédentes), mais réutilise exactement le mécanisme déjà éprouvé par `marvin:open-main`.
- Backend (port 8005, mission Code Workspace) non touché.

### Rollback

- `git checkout -- app/avatar/page.jsx desktop-avatar/main.cjs desktop-avatar/preload.cjs`
  restaure l'état d'avant cette entrée.

## 2026-07-21 — v2.256.0 — Démarrage par l'avatar et audit global de consolidation

### Demande et périmètre

- Corriger le démarrage de Marvin depuis l'avatar.
- Établir un état de l'ensemble du code avant toute discussion de découpage ; aucune extraction
  de `main.py` ou d'un autre module n'est autorisée dans ce lot.
- Comparer les options aux documentations officielles FastAPI, Starlette, Next.js, React et
  pytest, puis proposer une trajectoire réversible.

### Diagnostic du démarrage

1. Marvin était arrêté sur 3000/8005 alors que l'avatar Electron tournait toujours.
2. La fenêtre affichait la page Chromium `ERR_CONNECTION_REFUSED`, pas `offline.html` : aucun
   bouton de démarrage Marvin n'était alors disponible.
3. Après ajout du retour hors ligne, le clic réel sur « Démarrer Marvin » a atteint l'IPC mais
   le journal a révélé une première erreur : les guillemets de `cmd.exe /s /c` étaient traités
   comme une partie littérale du nom du batch.
4. Après correction des arguments, FastAPI démarrait mais pas Next.js. Deux processus
   `find.exe` restaient bloqués dans `netstat | find | find`, empêchant d'atteindre
   `npm run dev` dans le contexte détaché Electron.

### Implémentation

- `desktop-avatar/main.cjs` : gestion de `did-fail-load` sur la navigation principale
  `/avatar`, retour vers `offline.html`, lancement asynchrone observable, journal de démarrage
  dans `%LOCALAPPDATA%\Marvin\DesktopAvatar\startup.log`, erreurs IPC explicites et arguments
  `cmd.exe` séparés.
- `desktop-avatar/offline.js` : gestion des rejets IPC et réactivation du bouton avec une erreur
  exploitable.
- `start.bat` : remplacement du pipeline `netstat/find` par `Get-NetTCPConnection`, et appel
  explicite de `npm run dev` pour préserver le flux batch.
- `scripts/test_desktop_avatar.mjs` : trois invariants supplémentaires (33 au total).
- `CODEBASE-CONSOLIDATION-AUDIT.md` : audit global, sources officielles, comparaison de trois
  stratégies et feuille de route avec portes de validation. Aucun déplacement de code.

### État global constaté

- 355 fichiers de projet inventoriés ; 107 fichiers Python backend ; 96 fichiers frontend.
- Points de concentration : `tools.py` 21 247 lignes, `main.py` 5 545, `database.py` 3 554,
  `agent.py` 3 188 et plusieurs pages JSX de 1 300 à 3 400 lignes.
- `main.py` conserve 69 routes directes et dépend de 62 modules locaux malgré 37 routeurs déjà
  extraits.
- Analyse AST backend : 889 captures générales, 13 `except:` nus, 277 gestionnaires silencieux.
- Frontend : 37 avertissements ESLint, 333 appels `fetch`, 67 composants clients.
- Absence constatée de `pyproject.toml`, configuration pytest/type checker et pipeline CI.

### Validations réellement exécutées

- `node --check desktop-avatar/main.cjs` et `offline.js` : succès.
- `npm run check:avatar` : 33/33 assertions.
- Parcours Electron réel : page hors ligne affichée, clic de démarrage reçu, journal produit ;
  les deux causes Windows ci-dessus ont été observées et isolées successivement.
- Lancement du même contrat `cmd.exe /d /c call start.bat` après correction : backend HTTP 200,
  frontend `/avatar` HTTP 200, Next.js 16.2.6 Turbopack prêt en 1,53 s.
- `npm run check:architecture` : 344 outils, 346 routes, 40 pages.
- `npm run check:quick` : 36/36 étapes.
- `npm run check:api` : 28/28 contrats.
- `npm run check:pages` : 40/40 pages.
- `npm run lint` : 0 erreur, 37 avertissements conservés et consignés pour discussion.

### Rollback

- Correction avatar/démarrage : restaurer `desktop-avatar/main.cjs`,
  `desktop-avatar/offline.js`, `scripts/test_desktop_avatar.mjs` et `start.bat` à leur état
  précédent. Cela réintroduit les deux pannes reproductibles ; rollback déconseillé.
- Audit : supprimer uniquement `CODEBASE-CONSOLIDATION-AUDIT.md` si le document n'est plus
  souhaité. Aucune architecture applicative n'a été modifiée.

## 2026-07-22 — v2.257.0 — Supervision idempotente du cycle de vie FastAPI

### Demande et décision

- L'utilisateur autorise la consolidation complète de Marvin, avec adaptation du plan selon
  les constats, sans perte de capacité et avec versionnage et documentation Markdown continus.
- La réécriture globale a été écartée au profit d'extractions progressives couvertes par des
  tests de caractérisation et un rollback par tranche.
- La première frontière retenue est le cycle de vie des workers : elle réduit le risque de
  doublons et de tâches orphelines sans déplacer leur logique métier.

### Constat réel

- Le `lifespan` de `backend/main.py` créait quinze tâches avec `asyncio.create_task`.
- La même liste de quinze variables était recopiée pour l'annulation puis l'attente.
- Aucun registre n'exposait le statut, le nombre de démarrages ou la dernière exception.
- Le nettoyage n'était pas protégé par `finally`; une exception propagée au point `yield`
  pouvait donc contourner la fermeture des ressources.

### Implémentation

- Nouveau `backend/runtime_supervisor.py`, indépendant de FastAPI et des domaines métier.
- Démarrage idempotent par nom, relance explicite après terminaison, collecte des exceptions,
  instantané borné de l'état et fermeture idempotente avec délai maximal.
- Les quinze workers existants sont enregistrés sans changement de fonction ni de paramètres.
- Le superviseur est disponible dans `app.state.runtime_supervisor` pour les diagnostics futurs.
- Le nettoyage du navigateur, de `coding_jobs` et des workers est garanti par `finally`.
- Nouveau test `scripts/test_runtime_supervisor.py`, commande npm dédiée et étape ajoutée à
  l'orchestrateur de validation.
- `ARCHITECTURE.md` et `AGENTS.md` décrivent la nouvelle frontière portable.

### Fichiers modifiés

- `backend/runtime_supervisor.py`
- `backend/main.py`
- `scripts/test_runtime_supervisor.py`
- `scripts/check_architecture.py`
- `scripts/check_marvin.py`
- `package.json`, `package-lock.json`, `backend/app_version.py`
- `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, `DEVELOPMENT-JOURNAL.md`

### Validation réalisée

- `scripts/test_runtime_supervisor.py` : succès sur l'idempotence, la relance, la collecte
  d'erreur, l'annulation et le double arrêt.
- Compilation ciblée de `runtime_supervisor.py`, `main.py` et du test : succès.
- `scripts/check_marvin.py --quick` : 37/37 étapes réussies, 108 fichiers Python compilés,
  344 outils, 346 routes, 40 pages et aucune erreur ESLint; les 37 avertissements historiques
  restent inchangés.
- Backend réel redémarré avec `backend/.venv/Scripts/python.exe` : `/api/health` HTTP 200,
  version `2.257.0`, Ollama disponible, 344 exécuteurs et 344 schémas d'outils.
- Le même health check observe réellement 15 workers : 12 boucles actives et 3 tâches
  ponctuelles terminées normalement.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.

## 2026-07-22 — v2.299.0 — Repository des connexions SSH

### Constat et décision

- Les accès SQLite SSH étaient encore inclus dans la façade monolithique `database.py`, alors
  que l'API, le domaine d'outils et le transport sont désormais séparés.
- Un repository injectable est retenu pour centraliser schéma compatible, transactions et
  distinction entre projections publiques et lecture interne avec secrets.

### Implémentation et validation isolée

- Nouveau `repositories/ssh_connections.py`; `database.py` réexporte les sept fonctions sans
  changement d'appelant. Les champs modifiables sont en liste blanche et les secrets vides ne
  remplacent jamais une valeur existante.
- Nouveau test sur SQLite temporaire : ancienne table, ajout de colonnes, CRUD, secrets,
  test/touch, champ interdit, rollback sur contrainte et identité de façade.
- Hygiène SQLite, domaine SSH, 11 routes et architecture : tous les contrôles réussissent.

### Rollback

- Revenir au commit v2.298. Aucun schéma destructif ni déplacement de données n'est réalisé.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 79/79 étapes réussies; compilation de 153 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 33380, version `2.299.0`, Ollama disponible et 15 workers.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.
- Frontend Next.js/Turbopack conservé en fonctionnement : page `/` HTTP 200.
- Journaux Uvicorn : démarrage complet, index des outils prêt et sauvegarde SQLite créée;
  aucune exception de worker observée.

### Rollback

- Restaurer le bloc `lifespan` précédent dans `backend/main.py`, retirer l'import du
  superviseur, supprimer `backend/runtime_supervisor.py` et son test, puis retirer les entrées
  de validation et ramener les métadonnées de version à `2.256.0`.

## 2026-07-22 — v2.258.0 — Extraction des workers de maintenance

### Périmètre

- Extraire un premier groupe cohérent de workers après validation du superviseur.
- Ne modifier ni les routes, ni les outils disponibles, ni les paramètres fonctionnels.

### Implémentation

- Nouveau `backend/runtime_workers.py` pour le préchauffage Ollama, l'index sémantique des
  outils, l'apprentissage nocturne, la sauvegarde SQLite, la consolidation mémoire et la
  tendance de santé.
- Les noms historiques privés restent importés dans `main.py` sous les mêmes alias.
- Les quinze enregistrements du superviseur et leurs noms stables sont couverts par test AST.
- Le test du préchauffage utilise un client HTTP simulé et confirme qu'un même modèle configuré
  pour chat et agent n'est chargé qu'une fois.
- Le test de l'index remplace le routeur sémantique et le délai, sans toucher Qdrant ni Ollama.

### Fichiers

- `backend/runtime_workers.py`, `backend/main.py`
- `scripts/test_runtime_workers.py`, `scripts/check_architecture.py`, `scripts/check_marvin.py`
- métadonnées de version et documentation portable.

### Validation réalisée avant versionnage

- `scripts/test_runtime_workers.py` : succès.
- Compilation Python ciblée : succès.
- `scripts/check_architecture.py` : 344 outils, 346 routes et 40 pages.

### Rollback

- Recopier les six fonctions depuis `runtime_workers.py` dans `main.py`, retirer leurs imports,
  supprimer le module et son test, puis revenir aux métadonnées `2.257.0`.

## 2026-07-22 — v2.259.0 — Extraction des workers e-mail et agenda

### Périmètre et décision

- Isoler uniquement les boucles de communication qui ne sont pas des endpoints FastAPI.
- Reporter l'extraction du moteur proactif, car ses fonctions sont aussi appelées directement
  par des routes et nécessitent un contrat de service distinct.

### Implémentation

- Nouveau `backend/communication_workers.py` : surveillance e-mail, automatisation planifiée,
  rappels d'événements, facteur de cadence et synchronisation des calendriers.
- Import sous les cinq noms historiques dans `main.py`; aucune route ni entrée d'outil modifiée.
- Conservation du délai initial, des intervalles minimaux, du contrôle d'activation explicite,
  du texte de notification et de la mise à jour persistante après notification.
- Nouveau `scripts/test_communication_workers.py` sans accès externe.

### Validation réalisée avant versionnage

- Test communication : façade exacte, cadence 0,25 minimale, repli 1,0 sur erreur, notification
  simulée et mise à jour de l'événement : succès.
- Compilation Python ciblée : succès.
- Invariants d'architecture : 344 outils, 346 routes, 40 pages.

### Rollback

- Restaurer les quatre workers et `_bg_scale` dans `main.py`, retirer leurs imports, supprimer
  `communication_workers.py` et son test, puis revenir aux métadonnées `2.258.0`.

## 2026-07-22 — v2.260.0 — Service proactif et correction de la voix

### Constat causal

- Le bloc proactif mélangeait configuration, planification, notifications, Telegram, TTS,
  conversion audio et état de déduplication dans `main.py`.
- `_tts_bytes` utilisait `DEFAULT_TTS_VOICES` sans import. Comme `_speak_backend` absorbait
  l'exception, le briefing pouvait être annoncé comme réussi sans produire de voix.
- La lecture utilisait `tempfile.mktemp` et un sous-processus ffmpeg sans délai maximal.

### Implémentation

- Nouveau `backend/proactive_service.py` avec contrats typés et responsabilités regroupées.
- Import explicite de la table officielle des voix depuis `api.voice`.
- Dossier temporaire privé automatiquement nettoyé pour MP3/WAV et ffmpeg borné à 60 secondes.
- Les sept noms consommés par le worker et les routes restent importés dans `main.py` sous les
  mêmes alias; les anciens corps dupliqués ont été retirés.
- Nouveau `scripts/test_proactive_service.py` sans sortie réelle.

### Validation réalisée avant versionnage

- Façade AST et absence des anciennes définitions dans `main.py` : succès.
- Heures calmes 22:00–07:00 : cas intérieur et extérieur réussis.
- Synthèse simulée : nettoyage Markdown, voix Denise réelle et concaténation des fragments.
- Briefing simulé : résumé, notification, Telegram et appel vocal exacts.
- Compilation ciblée et invariants d'architecture : succès, 344 outils et 346 routes.

### Rollback

- Restaurer le bloc proactif dans `main.py`, importer explicitement `DEFAULT_TTS_VOICES`, retirer
  `proactive_service.py` et son test, puis revenir aux métadonnées `2.259.0`.

## 2026-07-22 — v2.261.0 — Extraction du moteur cron et des reprises longues

### Périmètre

- Terminer la consolidation du cycle de vie en retirant le dernier worker métier de `main.py`.
- Préserver strictement les règles de reprise et de confirmation déjà validées.

### Implémentation

- Nouveau `backend/cron_runtime.py` : tour agentique drainé, tick de reprise longue et boucle
  cron standard.
- Conservation du délai de 180 secondes, du compteur `_stall_count`, de la mise en pause après
  trois passages sans progrès et du message demandant une validation humaine.
- Conservation de `db.log_execution`, `run_count`, `last_result` borné à 500 caractères et du
  calcul centralisé de `next_run`.
- Les trois alias historiques restent importés dans `main.py`; les anciens corps sont retirés.
- Nouveau `scripts/test_cron_runtime.py` sans exécution d'outil réel.

### Validation réalisée avant versionnage

- Job long mal formé désactivé avec erreur persistée : succès.
- Mission longue sans étape restante désactivée et notification simulée : succès.
- Job standard simulé : arguments, exécution, journal, prochaine échéance et compteur validés.
- Compilation ciblée et invariants : succès, 344 outils, 346 routes, 40 pages.

### Validation complète après versionnage

- `scripts/check_marvin.py --quick` : 41/41 étapes réussies, 111 fichiers Python compilés,
  aucune erreur ESLint et 37 avertissements historiques inchangés.
- Backend réel redémarré depuis le `.venv` : version `2.261.0`, 15 workers observés et Ollama
  disponible.
- `scripts/smoke_test_api.py` sur le processus redémarré : 28/28 contrats HTTP réussis.
- Frontend Next.js/Turbopack conservé actif pendant toute la validation.

### Rollback

- Restaurer les trois fonctions cron dans `main.py`, retirer leurs imports, supprimer
  `cron_runtime.py` et son test, puis revenir aux métadonnées `2.260.0`.

## 2026-07-22 — v2.262.0 — Premier domaine extrait de tools.py

### Décision

- Conserver `TOOLS_REGISTRY` et `TOOLS_SPEC` comme littéraux dans `tools.py` pendant la migration.
- Extraire d'abord un domaine peu couplé afin de valider la façade avant les domaines système,
  documents ou e-mail beaucoup plus risqués.

### Implémentation

- Nouveau package `backend/tool_domains/` et domaine `quiz.py`.
- `quiz_generate` reçoit le générateur texte par injection; le domaine ne dépend donc jamais de
  `tools.py` et ne crée aucune boucle d'import.
- Les trois outils SQLite sont réexportés directement et le registre historique pointe vers les
  mêmes variables publiques.
- Validation explicite de `count` et contrôle que la sortie LLM JSON est bien une liste.
- Nouveau `scripts/test_tool_domain_quiz.py`.

### Validation réalisée avant versionnage

- Façade et quatre entrées du registre : succès.
- Génération simulée avec préambule autour du JSON, création de deux fiches et paramètres du
  modèle : succès.
- Fiche suivante, réponse et statistiques simulées : succès.
- Compilation ciblée et invariants : 344 outils, 346 routes, 40 pages.

### Rollback

- Restaurer les quatre fonctions dans `tools.py`, retirer l'import `tool_domains.quiz`, supprimer
  le package et son test, puis revenir aux métadonnées `2.261.0`.

## 2026-07-22 — v2.263.0 — Domaine Base de connaissances IT

### Implémentation

- Nouveau `backend/tool_domains/it_knowledge.py` pour les quatre outils `it_kb_*`.
- Réexport direct par `tools.py`; registre et spécifications inchangés.
- Conservation du score de notation/usage et des bonus open source et souveraineté.
- `limit` est validé et borné entre 1 et 100.
- Nouveau `scripts/test_tool_domain_it_knowledge.py`.

### Validation réalisée avant versionnage

- Façade et quatre entrées du registre : succès.
- Recherche, regroupement par catégorie, déduplication et ajout simulés : succès.
- Classement : une solution open source, auto-hébergée et RGPD est classée avant une solution
  payante mieux notée lorsque ces contraintes figurent dans la demande.
- Compilation ciblée et invariants : 344 outils, 346 routes, 40 pages.

### Rollback

- Restaurer les quatre fonctions dans `tools.py`, retirer le module et son test, puis revenir
  aux métadonnées `2.262.0`.

## 2026-07-22 — v2.264.0 — Migrations SQLite transactionnelles

### Contexte et constats

- Le schéma était créé à la demande par de nombreux `_ensure_*` Python et partiellement par
  `lib/database/init.js`, sans historique ordonné ni détection de dérive.
- Une migration SQL échouée ne disposait pas d'un contrat de rollback testable.
- Sur une base vierge, l'initialiseur JavaScript tentait de créer `idx_cron_enabled` avant la
  table `cron_jobs`, ce qui pouvait interrompre une installation neuve.

### Décision et implémentation

- Ajout de `backend/db_migrations.py` : catalogue strictement ordonné, empreinte SHA-256,
  table `schema_migrations`, `PRAGMA user_version`, refus d'un schéma inconnu et savepoint par
  migration.
- La migration 1 adopte sans destruction le schéma historique. La migration 2 crée le schéma
  cœur complet lorsque Python démarre le premier. Tous les `CREATE` sont idempotents et ne
  réécrivent aucune donnée existante.
- `database._init_tables()` conserve les initialiseurs historiques puis enregistre/applique le
  catalogue. Cette séquence évite de supprimer prématurément les compatibilités anciennes.
- L'index Cron de `lib/database/init.js` est déplacé après la création de `cron_jobs`.
- Les libellés français des notifications de tâches longues, altérés pendant l'extraction
  v2.261, ont été restaurés.

### Sécurité des données et rollback

- `PRAGMA quick_check` de la base réelle avant la nouvelle tranche : `ok`.
- Sauvegarde cohérente créée via `POST /api/backups` et l'API native `sqlite3.backup()` :
  `data/backups/secretary_20260722_011932.db` (64 332 Kio).
- Rollback applicatif : revenir au code `2.263.0`. Rollback des données si nécessaire : utiliser
  l'endpoint de restauration avec cette sauvegarde; ne jamais remplacer le fichier SQLite à
  chaud par une copie brute.

### Validation isolée réalisée avant versionnage

- Application puis seconde exécution sans effet : succès.
- Détection d'un checksum modifié et d'un schéma plus récent : succès.
- SQL volontairement invalide : rollback confirmé, aucune table partielle conservée.
- Base Python vierge : schéma cœur, clés étrangères et `quick_check` valides.
- Base Next.js vierge : création de toutes les tables et de l'index Cron réussie.
- Invariants d'architecture : 344 outils, 346 routes et 40 pages.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 45/45 étapes réussies et 116 fichiers Python compilés.
- ESLint : 0 erreur; 37 avertissements historiques inchangés et hors de cette tranche.
- Backend réel redémarré depuis `backend/.venv` : Marvin `2.264.0`, Ollama disponible,
  344 outils et 15 workers supervisés.
- Base réelle après démarrage : migrations 1 et 2 enregistrées, `user_version=2`,
  `PRAGMA quick_check=ok` et aucune violation de clé étrangère.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.
- Frontend Next.js/Turbopack conservé actif et vérifié en HTTP 200; aucun build concurrent lancé.

## 2026-07-22 — v2.265.0 — Frontière SQLite et repository conversations

### Objectif

- Réduire progressivement `database.py` sans réécrire les 344 outils ni les routeurs.
- Séparer la politique de connexion, la transaction et la persistance métier.

### Implémentation

- Nouveau `backend/db_connection.py` : connexion WAL, `foreign_keys=ON`, délai SQLite explicite
  de 10 secondes, conversion de ligne et context manager avec commit/rollback/fermeture.
- Nouveau package `backend/repositories/` et `ConversationRepository` injectable.
- Les douze fonctions conversations/messages sont réexportées par `database.py` sous leur nom
  historique. Les corps dupliqués ont été retirés; les consommateurs restent inchangés.
- Un rollback est aussi effectué lors d'une interruption dérivée de `BaseException`, avant la
  fermeture garantie de la connexion.

### Validation isolée réalisée avant versionnage

- Façade AST : douze exports présents et aucune redéfinition résiduelle dans `database.py`.
- CRUD conversation, épinglage, recherche titre/contenu et déduplication : succès.
- Sérialisation/désérialisation des appels et résultats d'outils : succès.
- Titrage silencieux sans modification de `updated_at` : succès.
- Rôle invalide : contrainte SQLite déclenchée et aucun message partiel conservé.
- Suppression de conversation : messages supprimés en cascade.
- Exception au milieu d'une transaction : écriture annulée; `busy_timeout` et clés étrangères
  confirmés sur la connexion suivante.
- Compilation ciblée et invariants : 344 outils, 346 routes et 40 pages.

### Rollback

- Restaurer la fabrique et les douze fonctions dans `database.py`, retirer `db_connection.py`,
  `repositories/` et leur test, puis revenir aux métadonnées `2.264.0`. Aucun rollback de
  données n'est requis : cette tranche ne modifie pas le schéma.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 46/46 étapes réussies, 0 erreur ESLint et 37
  avertissements historiques inchangés.
- Backend réel redémarré : version `2.265.0`, 344 outils, 15 workers et Ollama disponible.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.
- Lecture réelle d'une conversation existante via le repository et l'API : identifiant et deux
  messages retournés correctement, sans mutation des données utilisateur.
- Base réelle : `quick_check=ok`, aucune violation de clé étrangère.
- Frontend Next.js/Turbopack : HTTP 200, conservé actif sans build concurrent.

## 2026-07-22 — v2.266.0 — Premières politiques pures de l'agent

### Décision

- Ne pas déplacer immédiatement `run_agent`, qui porte le protocole SSE et de nombreux contrats.
- Extraire d'abord les décisions pures pouvant être prouvées sans Ollama, Qdrant ou SQLite.

### Implémentation

- Nouveau `backend/agent_policy.py` : titre provisoire et détection d'un nom d'outil exact avec
  bornes de tokens, afin qu'un fragment comme `profile_findings` ne déclenche pas `file_find`.
- La politique « donner la commande sans l'exécuter » rejoint `intent_guard.py`; les négations
  « ne lance rien » et « sans exécuter » restent prioritaires sur le verbe aperçu dans le texte.
- `agent.py` importe les fonctions sous les trois alias historiques consommés par `run_agent`.
- La normalisation NFKD du filtre d'outils réutilise `cloud_routing.strip_accents` au lieu d'une
  seconde implémentation locale.

### Validation isolée réalisée avant versionnage

- Titres vides, courts et tronqués à six mots : succès.
- Outils cités avec underscore, espaces et casse variable : succès; sous-chaîne refusée.
- Demande de commande comme texte avec négation : aucun outil d'exécution.
- Demande explicite « puis exécute-la » : exécution non bloquée par cette politique.
- Garde-fous d'intention : 21 scénarios réussis.
- Ultra débridé : tests cloud-only toujours réussis, aucun repli local introduit.
- `agent.py` : 3 127 lignes, aucune redéfinition des trois politiques extraites.
- Compilation ciblée et invariants : 344 outils, 346 routes et 40 pages.

### Rollback

- Restaurer les trois fonctions dans `agent.py`, retirer `agent_policy.py` et les nouveaux tests,
  puis revenir aux métadonnées `2.265.0`. Aucun schéma ni donnée n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 47/47 étapes réussies; compilation, dépendances et
  frontend validés, 0 erreur ESLint et 37 avertissements historiques inchangés.
- Backend réel redémarré : version `2.266.0`, 344/344 contrats d'outils et 15 workers.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.
- Conversations existantes lisibles et frontend Turbopack en HTTP 200.
- Journal uvicorn : démarrage propre, aucune exception applicative observée.

## 2026-07-22 — v2.267.0 — Fermeture garantie des connexions SQLite

### Constat

- Deux chemins Google Calendar dans `tools.py` et le diagnostic OAuth dans
  `api/connections.py` enchaînaient `db.get_conn().execute(...)`.
- La ligne SQLite était lue, mais l'objet connexion n'était ni stocké ni fermé explicitement.
  Sous Windows et en usage prolongé, ce pattern peut accumuler des handles et prolonger la vie
  des fichiers WAL/SHM.

### Correction

- Les trois lectures utilisent désormais le context manager central `with db.db()`.
- Nouveau contrôle AST `scripts/test_db_connection_hygiene.py` : aucun appel direct à
  `get_conn()` n'est permis dans le backend hors de sa fabrique.

### Validation isolée réalisée avant versionnage

- Scan de tous les fichiers Python backend : aucune connexion directe restante.
- Compilation de `tools.py` et `api/connections.py` : succès.
- Orchestrateur e-mail : OAuth2, en-têtes RFC, secrets masqués et simulation réussis.
- Invariants : 344 outils, 346 routes et 40 pages.

### Rollback

- Restaurer les trois lectures directes et retirer le contrôle AST, puis revenir à `2.266.0`.
  Aucun schéma ni contenu utilisateur n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 48/48 étapes réussies; 0 erreur ESLint et 37
  avertissements historiques inchangés.
- Backend réel redémarré : version `2.267.0`, 344/344 outils et 15 workers.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, y compris connexions masquées,
  agenda et orchestrateur e-mail.
- Frontend Next.js/Turbopack conservé actif; aucun build concurrent exécuté.



## 2026-07-22 — v2.268.0 — Sécurité déterministe extraite de l'agent

### Objectif et décision

- Réduire `agent.py` par responsabilité sans déplacer la boucle SSE principale.
- Isoler les contrôles qui doivent rester déterministes même lorsque le LLM change.

### Implémentation

- Nouveau `backend/agent_safety.py` avec index immuable des paramètres obligatoires construit
  depuis `TOOLS_SPEC`, validateur injectable et scanner des scripts/documents.
- `agent.py` conserve les deux alias historiques utilisés dans `run_agent`; les anciennes
  fonctions et tables regex dupliquées sont retirées.
- Une valeur d'arguments qui n'est pas un objet JSON est maintenant refusée explicitement.
- Les paramètres texte obligatoires composés uniquement d'espaces restent considérés absents.

### Validation isolée réalisée avant versionnage

- Argument valide, absent, vide, outil inconnu et arguments non objet : succès.
- Script sans bloc de code : pas de faux positif dans une réponse en prose.
- Bloc Bash avec `chmod -R 777` et `ufw disable` : deux alertes détectées.
- `$(date)` accepté dans un script, mais signalé dans un document statique.
- Façade AST : aucune redéfinition résiduelle dans `agent.py`.
- Code Forge, 21 garde-fous d'intention et compilation ciblée : succès.
- Invariants : 344 outils, 346 routes et 40 pages.

### Rollback

- Restaurer le validateur, les motifs et le scanner dans `agent.py`, supprimer
  `agent_safety.py` et son test, puis revenir à `2.267.0`. Aucun schéma ni donnée n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 49/49 étapes réussies; compilation, dépendances et
  frontend validés, 0 erreur ESLint et 37 avertissements historiques inchangés.
- Backend réel redémarré : version `2.268.0`, 344/344 outils et 15 workers.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.
- Frontend Next.js/Turbopack : HTTP 200; journal uvicorn sans exception au démarrage.

## 2026-07-22 — v2.269.0 — Protocole UI, Ollama et SSE extrait

### Implémentation

- Nouveau `backend/agent_protocol.py` pour la conversion des messages et l'encodage SSE.
- Conservation des formats `toolInvocations` frontend, `tool_calls` persistés, messages outil,
  texte simple, `parts` et images data URL.
- Les fragments multimodaux et appels d'outils qui ne sont pas des objets sont ignorés sans
  interrompre la réponse complète.
- `agent.py` conserve `_to_ollama_messages` et `_sse` comme alias importés; les anciens corps
  sont retirés.

### Validation isolée réalisée avant versionnage

- Texte, image base64, outil frontend et résultat Unicode : succès.
- Appel d'outil rechargé depuis SQLite : nom et arguments conservés.
- SSE : préfixe `data:`, Unicode conservé, saut de ligne du contenu échappé et terminaison vide.
- Façade AST : aucune redéfinition dans `agent.py`.
- Navigation Chat : 8 assertions; Mission Tracker : 4; présentation Chat : 14.
- Compilation ciblée et invariants : 344 outils, 346 routes et 40 pages.

### Rollback

- Restaurer les deux fonctions dans `agent.py`, supprimer `agent_protocol.py` et son test,
  puis revenir à `2.268.0`. Aucun schéma ni contenu utilisateur n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 50/50 étapes réussies; 0 erreur ESLint et 37
  avertissements historiques inchangés.
- Backend réel redémarré : version `2.269.0`, 344/344 outils et 15 workers.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis après redémarrage.
- Frontend Next.js/Turbopack conservé actif; aucun build concurrent exécuté.

## 2026-07-22 — v2.270.0 — Routage des profils et modèles extrait

### Contexte et décision

- Poursuivre la réduction progressive de `agent.py` sans réécrire la boucle agentique.
- Isoler les décisions déterministes de profil et l'inventaire Ollama, tout en laissant
  `cloud_routing.py` autoritaire pour la confidentialité et la sélection Cloud.
- Conserver les alias privés utilisés par `main.py` et `run_agent` afin d'éviter une rupture
  de compatibilité pendant la consolidation.

### Implémentation

- Nouveau `backend/agent_routing.py` : cache d'inventaire Ollama, disponibilité exacte des
  modèles, replis ordonnés, profils chat/agent/analysis/vision et contexte sensible récent.
- `agent.py` importe les décisions sous les anciens noms `_detect_profile`,
  `_refresh_model_cache`, `_pick_available` et les façades de confidentialité historiques.
- Les tables de mots-clés et les cinq anciennes fonctions sont retirées de `agent.py`, soit
  plus de 300 lignes de responsabilité distincte supprimées sans suppression fonctionnelle.
- Nouveau contrôle `scripts/test_agent_routing.py`, intégré aux commandes npm, au socle
  d'architecture et au contrôle consolidé.

### Validation réalisée

- Inventaire Ollama simulé : noms complets et familles sans tag conservés.
- Cache vide : compatibilité de démarrage préservée; repli ordonné vérifié.
- Profils sans message, conversation courte, analyse, action et vision : vérifiés.
- Sensibilité du message courant et d'un outil e-mail dans l'historique : vérifiée.
- Mode Ultra strictement cloud, Council cinq modèles et 21 garde-fous d'intention : réussis.
- `scripts/check_marvin.py --quick` : 51/51 étapes réussies; 123 fichiers Python compilés,
  dépendances cohérentes, 0 erreur ESLint et 37 avertissements historiques inchangés.
- Backend réel redémarré : version `2.270.0`, Ollama disponible, 344/344 outils et 15 workers.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis après redémarrage.
- Frontend Next.js/Turbopack conservé actif et répond en HTTP 200; aucun build concurrent.

### Rollback

- Restaurer les constantes et fonctions de routage dans `agent.py`, retirer
  `agent_routing.py` et son test, puis revenir à `2.269.0`. Aucun schéma ni contenu utilisateur
  n'est modifié par cette tranche.

## 2026-07-22 — v2.271.0 — Prompt système extrait et rendu déterministe

### Contexte et décision

- Isoler la construction du prompt sans modifier la boucle LLM ni les règles existantes.
- Éliminer l'appel `locale.setlocale`, qui modifiait un état global partagé et dépendait des
  locales installées sur chaque machine Windows.

### Implémentation

- Nouveau `backend/agent_prompt.py` : chemins utilisateur dynamiques, permissions, mémoires,
  règles de comportement et date française.
- `agent.py` conserve `_build_system_prompt` comme alias importé; les imports `os` et `Path`
  devenus inutiles y sont retirés.
- La date utilise des tables françaises immuables et accepte une horloge optionnelle pour les
  tests, sans changer la signature utilisée par Marvin.
- Nouveau `scripts/test_agent_prompt.py`, intégré aux contrôles npm, architecture et qualité.

### Validation isolée réalisée avant versionnage

- Profils Sécurisé, Standard, Expert et valeur inconnue : contrats vérifiés.
- Chemins home/Bureau injectés depuis un faux poste Windows : vérifiés.
- Mémoire présente/absente, règles anti-erreur, Code Workspace et français : vérifiés.
- Date injectée du 22 juillet 2026 : résultat exact `mercredi 22 juillet 2026`.
- Façade `_build_system_prompt` importable depuis `agent.py`, compilation ciblée réussie.

### Rollback

- Restaurer la fonction dans `agent.py`, supprimer `agent_prompt.py` et son test, puis revenir
  à `2.270.0`. Aucun schéma, paramètre ou contenu utilisateur n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 52/52 étapes réussies; 124 fichiers Python compilés,
  dépendances cohérentes, 0 erreur ESLint et 37 avertissements historiques inchangés.
- Backend réel redémarré : version `2.271.0`, Ollama disponible, 344/344 outils et 15 workers.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis après redémarrage.
- Frontend Next.js/Turbopack : HTTP 200; aucun build concurrent exécuté.

## 2026-07-22 — v2.272.0 — Sélection des outils LLM extraite

### Contexte et décision

- Sortir de `agent.py` la matrice de routage qui relie les formulations utilisateur aux
  outils exposés au modèle, sans changer les 344 contrats d'outils.
- Corriger l'ordre non déterministe des ensembles quand `max_tools` tronque la sélection.

### Implémentation

- Nouveau `backend/agent_tool_selection.py` : outils universels, repli courant, matrice de
  domaines, normalisation, routage sémantique/appris et plafond par profil.
- `agent.py` conserve `_filter_relevant_tools` comme alias importé et `_strip_accents` pour
  ses autres décisions; environ 670 lignes de responsabilité dédiée en sont retirées.
- Les groupes prioritaires sont triés avant troncature. À demande, configuration et catalogue
  identiques, la liste retenue ne dépend plus du hash seed du processus Python.
- Nouveau `scripts/test_agent_tool_selection.py`, intégré au contrôle consolidé.

### Validation isolée réalisée avant versionnage

- Aucun message : catalogue complet historique conservé.
- Recherche web récente : `web_search`, `web_browse` et `web_research` présents.
- Code Workspace : démarrage, statut et contrôle présents.
- E-mail : comptes, liste et lecture présents.
- Plafond à trois outils sur catalogue simulé : résultat stable `[a, b, z]` sur deux passages.
- Façade importable, compilation ciblée, prompt, routage modèle et 21 intentions : réussis.

### Rollback

- Restaurer la matrice et le filtre dans `agent.py`, supprimer le module et son test, puis
  revenir à `2.271.0`. Aucun schéma ni contenu utilisateur n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 53/53 étapes réussies; compilation, dépendances et
  frontend validés, 0 erreur ESLint et 37 avertissements historiques inchangés.
- Backend réel redémarré : version `2.272.0`, Ollama disponible, 344/344 outils et 15 workers.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis après redémarrage.
- Frontend Next.js/Turbopack : HTTP 200; aucun build concurrent exécuté.

## 2026-07-22 — v2.273.0 — Reçus idempotents des actions du chat

### Constat et décision

- Le frontend créait déjà un identifiant unique par message utilisateur, mais ne le
  transmettait pas à `/api/chat`.
- Le backend recréait donc le message et des identifiants d'appels aléatoires à chaque
  requête. Après interruption ou rejeu réseau, aucune preuve ne permettait d'empêcher une
  seconde création, un second envoi ou une seconde commande.
- Retenir un reçu durable par `requestId + conversation + outil + hash des arguments`.

### Implémentation

- Migration SQLite 3 : colonne `messages.client_request_id`, index unique partiel et table
  `action_receipts` avec états `started`, `completed` et `unknown`.
- `ChatContext` et `useSecretary` transmettent l'identifiant du message courant; FastAPI le
  valide puis le transmet à `run_agent`.
- Le repository de conversations retourne le message existant pour le même identifiant et
  refuse un même identifiant associé à un contenu divergent.
- `backend/action_replay.py` réserve atomiquement les actions à effet de bord. Un reçu terminé
  est réutilisé, un doublon concurrent est refusé et un reçu appartenant à un ancien processus
  devient `unknown` sans nouvelle exécution.
- Seul le hash canonique des arguments est stocké. Les clés de secrets sont masquées dans les
  résultats persistés. Une panne d'écriture du reçu après l'action ne masque pas le résultat
  déjà obtenu et n'entraîne pas un rejeu implicite.
- Le tri des messages utilise aussi `rowid` pour départager deux écritures dans la même seconde.

### Validation isolée réalisée avant versionnage

- Même action appelée deux fois : exécuteur appelé une seule fois, second résultat réutilisé.
- Deux appels concurrents : le second reçoit `action_in_progress` sans exécution.
- Reçu `started` d'un ancien processus : `action_outcome_unknown`, aucun nouvel effet.
- Lecture non gardée : deux exécutions autorisées.
- Secret du résultat : valeur masquée dans le reçu rejoué.
- Échec de persistance après action : succès utilisateur conservé avec avertissement de reçu.
- Message avec même requestId : une seule ligne; contenu divergent refusé.
- Migrations, repository, intentions, cloud-only, compilation et lint sans erreur : réussis.

### Rollback

- Le code peut revenir à `2.272.0`; les colonnes et la table additives peuvent rester sans
  être utilisées. Pour un rollback physique hors ligne, restaurer la sauvegarde SQLite créée
  avant migration. Aucune donnée existante n'est transformée ou supprimée.

### Validation complète et réelle après versionnage

- Sauvegarde SQLite cohérente vérifiée par `quick_check` dans
  `data/backups/secretary_before_v2273_consistent_20260722_100452.db`.
- `scripts/check_marvin.py --quick` : 54/54 étapes réussies; compilation, dépendances et
  frontend validés, 0 erreur ESLint et 37 avertissements historiques inchangés.
- Backend réel redémarré : version `2.273.0`, Ollama disponible, 344/344 outils et 15 workers.
- Base réelle : `user_version=3`, table `action_receipts` présente et `quick_check=ok`.
- OpenAPI réel : `ChatRequest` expose `requestId` avec les champs historiques inchangés.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis après redémarrage.
- Frontend Next.js/Turbopack : HTTP 200; aucun build concurrent exécuté.

## 2026-07-22 — v2.274.0 — Tours de chat durables et détachables

### Constat et décision

- Les reçus v2.273 empêchaient un double effet de bord, mais le générateur agentique restait
  possédé par la connexion HTTP. Une fermeture ou coupure du navigateur pouvait donc annuler
  le travail avant que sa réponse soit persistée.
- Deux approches ont été évaluées : conserver uniquement l'état React global, simple mais
  incapable de survivre à une vraie coupure; ou détacher le producteur côté backend avec un
  journal durable. La seconde est retenue car elle couvre aussi l'avatar et les reconnexions.

### Implémentation

- Migration SQLite 4 : `chat_turns` conserve le propriétaire et l'état du tour;
  `chat_turn_events` conserve les événements SSE ordonnés par un curseur monotone.
- Nouveau `backend/chat_turn_runtime.py` : réservation atomique, producteur `asyncio`
  indépendant du client, rattachement au même `requestId`, rejeu après curseur et arrêt propre.
- Une reconnexion au même payload ne relance pas le LLM. La réutilisation divergente d'un
  `requestId` est refusée. Un producteur perdu après redémarrage devient `interrupted` et émet
  une erreur explicite, sans reproduire une action dont le résultat pourrait être ambigu.
- Le frontend retente une seule fois la connexion initiale avec le même `requestId`. Les
  journaux terminaux sont purgés après 30 jours; les messages utilisateur restent intacts.
- Le chemin historique sans `requestId` reste accepté pour compatibilité avec les appels
  internes existants.

### Validation isolée réalisée avant versionnage

- Client détaché après le premier fragment : producteur poursuivi jusqu'à `done`.
- Reconnexion après le curseur 1 : événements 2 et 3 relus, un seul démarrage du producteur.
- Payload divergent avec le même identifiant : refus déterministe.
- Ancien propriétaire simulé : tour interrompu et non relancé.
- Migrations 1 à 4, initialiseur SQLite Next.js, compilation Python et ESLint : réussis.

### Rollback

- Revenir à `2.273.0`. Les deux tables additives peuvent rester inutilisées sans modifier les
  conversations. Pour un rollback physique, arrêter Marvin puis restaurer la sauvegarde SQLite
  cohérente précédente. Aucun message n'est supprimé par l'implémentation.

### Validation complète et réelle après versionnage

- Sauvegarde SQLite cohérente :
  `data/backups/secretary_before_v2274_20260722_102352.db` (`quick_check=ok`).
- `scripts/check_marvin.py --quick` : 55/55 étapes réussies, 127 fichiers Python compilés,
  dépendances cohérentes, 0 erreur ESLint et 37 avertissements historiques inchangés.
- Backend réel redémarré : version `2.274.0`, Ollama disponible, 344/344 outils et 15 workers.
- Base réelle : `user_version=4`, tables de tours présentes et `quick_check=ok`.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis; frontend Turbopack HTTP 200.
- Tour réel sans outil : 11 événements numérotés, conversation attribuée et état final
  `completed`; les données de test ont ensuite été supprimées.

## 2026-07-22 — v2.275.0 — Reconnexion SSE frontend au curseur

### Constat et décision

- La v2.274 conservait le producteur et ses événements, mais l'UI ne retentait automatiquement
  que l'établissement initial du POST. Une rupture de transport après plusieurs fragments
  laissait le backend terminer sans rattacher l'affichage courant.
- Centraliser le transport dans un générateur JavaScript partagé évite deux implémentations
  divergentes entre `ChatContext` et `useSecretary`.

### Implémentation

- Nouveau `lib/chatStream.js` : parsing SSE, curseur du dernier événement effectivement livré,
  deux reconnexions bornées et propagation immédiate d'une annulation utilisateur.
- Chaque reconnexion renvoie `afterEvent`; le backend ne restitue que les séquences suivantes.
  Le texte, les outils, le raisonnement et la synthèse vocale ne reçoivent donc aucun doublon.
- `ChatContext` et `useSecretary` conservent leurs projections UI historiques mais délèguent
  désormais le transport au même générateur.

### Validation isolée réalisée avant versionnage

- Flux simulé coupé après `turnSeq=1`, puis repris : deux connexions, second POST avec
  `afterEvent=1`, événements visibles `text`, `text`, `done`, contenu final `AB` sans doublon.
- ESLint : 0 erreur.

### Rollback

- Revenir à `2.274.0` et restaurer les lecteurs SSE locaux dans les deux hooks. Aucun schéma
  SQLite supplémentaire n'est introduit par cette version.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 56/56 étapes réussies, 127 fichiers Python compilés,
  dépendances cohérentes, 0 erreur ESLint et 37 avertissements historiques inchangés.
- Backend réel redémarré : version `2.275.0`, Ollama disponible, 344/344 outils et 15 workers.
- Frontend Next.js/Turbopack : `/market` répond HTTP 200. Le navigateur intégré refuse le
  rechargement de `localhost` par politique d'URL; aucune tentative de contournement effectuée.

## 2026-07-22 — v2.276.0 — Budget d'autonomie Cortex adaptatif

### Constat et décision

- `agent.py` utilisait le même plafond de 10 itérations pour une explication instantanée et
  une mission complexe. Le modèle pouvait donc surconsommer sur une tâche simple ou manquer
  d'espace pour vérifier une mission profonde.
- Un travail sans limite a été écarté : il augmente les coûts Cloud, les boucles d'outils et
  le risque d'effets répétés. Le compromis retenu est un budget croissant, observable et borné.

### Implémentation

- `cortex.execution_budget` compile les profils instant/standard/deep/mission en plafonds de
  3/10/16/24 étapes et 120/600/1800/3600 secondes.
- Une autonomie explicitement `mission` reçoit le budget mission même si l'effort n'était pas
  épinglé. Les exigences de preuves et de revue sont également exposées dans le contrat.
- La boucle agentique utilise le budget compilé, arrête avant une nouvelle étape si le temps
  est épuisé et conserve la synthèse finale historique sans outils.
- La provenance indique étapes consommées, durée et cause d'arrêt
  (`criteria_satisfied`, `max_tool_steps` ou `max_wall_seconds`).

### Validation isolée réalisée avant versionnage

- Budgets des quatre profils et croissance temporelle vérifiés sans appel LLM.
- Sources primaires marquées comme preuve requise; instruction d'arrêt anticipé injectée.
- Garde-fous d'intention, prompt agent et compilation Python : réussis.

### Rollback

- Revenir à `2.275.0` et réutiliser `config.MAX_TOOL_STEPS=10`. Aucun schéma ni contenu
  utilisateur n'est modifié par cette version.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 56/56 étapes réussies, 127 fichiers Python compilés,
  dépendances cohérentes, 0 erreur ESLint et 37 avertissements historiques inchangés.
- Backend réel redémarré : version `2.276.0`, Ollama disponible, 344/344 outils et 15 workers.
- Tour Cloud réel en effort instant : contrat 3 étapes/120 secondes, une étape consommée,
  arrêt `criteria_satisfied`; conversation et journal de test supprimés après validation.

## 2026-07-22 — v2.277.0 — Frontière d'exécution du moteur agentique

### Demande et remise en cohérence

- L'utilisateur a rappelé que le chantier prioritaire est la consolidation globale du code
  selon les principes d'architecture observables chez OpenAI, Anthropic et Google, et non
  l'accumulation de fonctionnalités Cortex isolées.
- L'option B de `CODEBASE-CONSOLIDATION-AUDIT.md` reste la décision directrice : migration
  incrémentale par façades et contrats, avec test et rollback à chaque frontière extraite.

### Références officielles et décision

- OpenAI Agents SDK sépare l'agent configuré du `Runner`, du stockage de session, des
  guardrails, des outils et du tracing par exécution.
- Anthropic recommande une boucle simple où le LLM conserve la liberté de décider, mais avec
  des outils composables, un état durable, des retours du monde réel et des évaluations. Son
  architecture Managed Agents distingue explicitement session, harness et sandbox.
- Google ADK sépare runtime/event loop, sessions, état temporaire, mémoire durable, outils,
  callbacks et observabilité.
- Pour Marvin, le compromis retenu n'est pas l'adoption d'un framework fournisseur : il s'agit
  de stabiliser les mêmes frontières dans l'architecture existante, compatible Ollama Cloud,
  Ollama local, Windows et les 344 outils actuels.

### Implémentation

- Nouveau `backend/agent_execution.py`, frontière unique entre décision du LLM et action :
  résolution du registre, reçu idempotent, classification des erreurs d'outillage et
  normalisation des appels d'outils écrits en texte par certains modèles.
- Le registre est injectable pour isoler les tests et préparer plusieurs runtimes sans état
  global substitué. La production conserve `TOOLS_REGISTRY` par défaut.
- `backend/agent.py` conserve les quatre alias historiques. Aucun appel interne, outil,
  permission, confirmation ni format SSE n'a changé.
- Nouveau test de caractérisation `scripts/test_agent_execution.py` : succès, outil inconnu,
  exception contrôlée, reçu, filtrage strict des outils autorisés, erreurs environnementales
  et compatibilité de façade.

### Validation isolée réalisée avant versionnage

- Compilation de `agent_execution.py`, `agent.py` et du test : réussie.
- Tests `agent_execution`, `agent_policy`, `agent_safety` et `agent_tool_selection` : réussis.
- `scripts/check_architecture.py` : Marvin 2.277.0, 344 outils, 346 routes, 40 pages et
  63 outils encadrés.
- `git diff --check` : aucune erreur de patch.

### Rollback

- Revenir au commit v2.276 et replacer les quatre fonctions derrière leurs alias dans
  `agent.py`. Aucun schéma SQLite, contenu utilisateur ou contrat réseau n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 57/57 étapes réussies; le nouveau test d'exécution
  agentique fait désormais partie de la porte centrale. ESLint reste à 0 erreur et conserve
  37 avertissements historiques hors périmètre.
- Backend réel redémarré : version `2.277.0`, Ollama disponible; frontend Turbopack HTTP 200.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.
- `agent.py` passe de 1 854 à 1 694 lignes sans suppression de fonctionnalité; la logique
  retirée est déplacée derrière des alias vers le nouveau module et couverte par test.

## 2026-07-22 — v2.278.0 — Revue indépendante extraite du runner

### Constat et décision

- `agent.py` contenait encore deux responsabilités distinctes de l'orchestration : construire
  et exécuter la revue d'une réponse, puis juger la cohérence d'une action sensible.
- OpenAI expose les output/tool guardrails comme politiques du run; Anthropic montre qu'un
  évaluateur apporte de la valeur lorsque la tâche dépasse la fiabilité du générateur; Google
  ADK sépare callbacks, outils, runtime et évaluations. Marvin adopte la même frontière sans
  rendre le critique obligatoire sur les réponses simples.

### Implémentation

- Nouveau `backend/agent_review.py` avec `review_response`, `review_action` et la sélection
  d'un modèle critique distinct parmi les modèles Cloud déjà configurés.
- Le générateur est injectable : les tests ne dépendent ni d'Ollama ni du réseau.
- Les limites existantes sont conservées : revue automatique des blocs de code, revue forcée
  par les contrats Cortex `verify`/`council_if_disagreement`, verdict insignifiant ignoré,
  panne du critique non bloquante et contrôle d'action limité à 200 caractères.
- `agent.py` garde `_run_critique_pass` et `_critique_action` comme alias de compatibilité.
- `scripts/test_agent_review.py` couvre le déclenchement, le modèle différent, OK, anomalie,
  sortie vide, timeout, action incohérente et façade. Le test est ajouté à `check_marvin.py`.

### Validation isolée réalisée avant versionnage

- Compilation de `agent_review.py`, `agent.py` et du test : réussie.
- Tests `agent_review`, `agent_execution` et `agent_safety` : réussis.
- `scripts/check_architecture.py` : Marvin 2.278.0, 344 outils, 346 routes, 40 pages et
  63 outils encadrés.
- `git diff --check` : aucune erreur de patch.

### Rollback

- Revenir au commit v2.277 et replacer les deux fonctions et leur prompt dans `agent.py`.
  Aucun schéma, message utilisateur, outil ni protocole réseau n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 58/58 étapes réussies, dont la nouvelle porte de revue;
  ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : version `2.278.0`, Ollama disponible; frontend Turbopack HTTP 200.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.
- `agent.py` passe de 1 694 à 1 612 lignes; les deux alias historiques sont toujours appelables.

## 2026-07-22 — v2.279.0 — Contexte de session et captures extraits

### Constat et décision

- La boucle `run_agent` gérait encore directement deux responsabilités d'état : résumer les
  messages sortis de la fenêtre de contexte et maintenir le cycle de vie des captures jointes.
- La séparation `Session`/`State`/`Memory` de Google ADK, les sessions du Runner OpenAI et la
  session append-only d'Anthropic convergent sur une frontière d'état indépendante du modèle.
  Marvin conserve sa base actuelle mais rend cette frontière explicite et injectable.

### Implémentation et corrections

- Nouveau `backend/agent_context.py` : compaction bornée, cache `convsum_*`, extraction des
  data URL, persistance, analyse parallèle et enregistrement des captures.
- Le générateur de résumé et l'analyseur sont injectables; aucun appel Cloud, Ollama, OCR ou
  SQLite réel n'est nécessaire aux tests unitaires.
- Conservation du comportement : minimum quatre messages, 40 anciens messages au maximum,
  500 caractères par message, cache réutilisé à moins de six messages d'écart et résumé borné
  à 1 500 caractères.
- Correction rencontrée pendant l'extraction : `conversation_id` était concaténé directement
  au chemin disque. Il est désormais limité à 128 caractères alphanumériques, tiret ou
  underscore; une valeur comme `../../outside` est refusée.
- Correction de résilience : si le décodage, l'analyse ou l'écriture SQLite échoue après la
  création du fichier, celui-ci est supprimé au lieu de rester orphelin.
- `agent.py` conserve les trois alias historiques et le même appel depuis `run_agent`.

### Validation isolée réalisée avant versionnage

- Compilation de `agent_context.py`, `agent.py` et du test : réussie.
- `scripts/test_agent_context.py` : compaction, cache, exclusion des messages outil, image,
  confinement du chemin, nettoyage après panne et façade réussis.
- Non-régression `agent_execution` et `agent_review` : réussie.

### Rollback

- Revenir au commit v2.278 et replacer les trois fonctions dans `agent.py`. Aucun schéma,
  message, capture existante ni contrat HTTP n'est migré par cette version.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 59/59 étapes réussies; ESLint 0 erreur et les
  37 avertissements historiques restent inchangés.
- Backend réel redémarré : version `2.279.0`, Ollama disponible; frontend Turbopack HTTP 200.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.
- `agent.py` passe de 1 612 à 1 522 lignes; les trois alias historiques sont appelables.

## 2026-07-22 — v2.280.0 — Préparation durable d'un tour extraite

### Constat et décision

- Le début de `run_agent` créait la conversation, interprétait trois formats de message,
  persistait l'entrée, traitait les captures, produisait deux événements SSE et lançait le
  titrage. Cette logique de session précédait toute décision LLM mais restait imbriquée dans
  le runner.
- Une frontière `PreparedTurn` est retenue : elle matérialise l'état durable obtenu avant
  orchestration, comme les objets de session/run des architectures de référence, sans imposer
  un SDK fournisseur à Marvin.

### Implémentation

- Nouveau `backend/agent_session.py` avec `PreparedTurn`, `extract_user_text`,
  `prepare_turn` et `upgrade_title`.
- `prepare_turn` restitue l'identifiant, le texte utilisateur et les événements initiaux.
  `run_agent` ne possède plus le détail de la création, des écritures et du titrage.
- La persistance conserve `client_request_id`; les captures réutilisent la frontière v2.279;
  le titre déterministe est écrit immédiatement puis amélioré dans une tâche enregistrée dans
  `_BG_LEARN_TASKS` afin d'éviter sa collecte prématurée.
- Correction de robustesse rencontrée : une partie multimodale non dictionnaire est ignorée
  au lieu de lever pendant l'extraction de texte.
- Les alias `_prepare_turn` et `_smart_title_upgrade` restent disponibles dans `agent.py`.

### Validation isolée réalisée avant versionnage

- Compilation de `agent_session.py`, `agent.py` et du test : réussie.
- `scripts/test_agent_session.py` : nouvelle conversation, conversation existante, formats
  multimodaux/parts, message idempotent, événements, captures, titre et tâche suivie réussis.
- Non-régression `agent_context` et `agent_execution` : réussie.

### Rollback

- Revenir au commit v2.279 et replacer le bloc initial ainsi que le titrage dans `agent.py`.
  Aucun schéma ni contrat HTTP n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 60/60 étapes réussies; ESLint 0 erreur et
  37 avertissements historiques inchangés.
- Backend réel redémarré : version `2.280.0`, Ollama disponible; frontend Turbopack HTTP 200.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.
- `agent.py` passe de 1 522 à 1 456 lignes et la préparation de tour reste accessible par façade.

## 2026-07-22 — v2.281.0 — Plan de tour déterministe extrait

### Constat et décision

- Après la préparation de session, `run_agent` mélangeait encore les décisions déterministes
  pré-LLM avec la résolution du modèle : interdiction d'outils, Council, reprise Workspace,
  contrat Cortex et budgets.
- Ces contraintes doivent être figées avant de donner sa liberté au modèle. Un `TurnPlan`
  explicite est donc créé comme entrée stable du futur Runner.

### Implémentation

- Nouveau `backend/agent_planning.py` avec `TurnPlan` et `compile_turn_plan`.
- Le module compile sans réseau ni stockage : outils cités, demande de commande sans exécution,
  suppression d'outils, Council, route/mode/mission Workspace, axes Cortex et plafonds.
- La règle de continuité reste stricte : si `code_workspace_control` reprend une mission, les
  outils susceptibles de créer une autre mission sont retirés du plan.
- `agent.py` projette temporairement le plan vers ses variables historiques; cette façade sera
  supprimée seulement lorsque le Runner recevra directement l'objet typé.
- `scripts/test_agent_planning.py` couvre contraintes combinées, suppression prioritaire,
  budgets, reprise Workspace, outil explicitement cité et façade.

### Validation isolée réalisée avant versionnage

- Compilation de `agent_planning.py`, `agent.py` et du test : réussie.
- Tests `agent_planning`, `intent_guards`, `cortex` et `agent_session` : réussis.

### Rollback

- Revenir au commit v2.280 et replacer la compilation des contraintes au début de `run_agent`.
  Aucun schéma, réglage, message ni contrat HTTP n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 61/61 étapes réussies; ESLint 0 erreur et
  37 avertissements historiques inchangés.
- Backend réel redémarré : version `2.281.0`, Ollama disponible; frontend Turbopack HTTP 200.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.
- `agent.py` passe de 1 456 à 1 424 lignes; le plan est disponible par façade typée.

## 2026-07-22 — v2.282.0 — Configuration modèle et confidentialité extraite

### Constat et décision

- Le Runner contenait encore plus de cent lignes de résolution auto/manuelle, confidentialité
  et repli. Ces décisions formaient un contrat unique mais implicite.
- Un `ModelConfig` typé devient la sortie unique : profil, modèle actif, température, label,
  modèle local de repli, verrou local, Ultra Cloud et sensibilité.

### Implémentation et correction rencontrée

- Nouveau `backend/agent_model_config.py`; `run_agent` appelle une seule résolution puis émet
  `ModelConfig.event()` avant de préparer le contexte Ollama.
- Les règles historiques sont conservées : routage Cloud par tâche, Hyper local prioritaire,
  Ultra strictement Cloud, Cortex local/hybrid_redacted et bascule avant résultat sensible.
- La première validation a détecté la disparition de l'alias `_detect_profile` attendu par la
  façade `agent.py`. Tous les alias de routage historiques ont été restaurés avant versionnage.
- Nouveau `scripts/test_agent_model_config.py` : manuel, température, Hyper local, Ultra Cloud,
  confidentialité locale, routage Cloud automatique et façade.

### Validation isolée réalisée avant versionnage

- Compilation du module, de `agent.py` et du test : réussie.
- Tests `agent_model_config`, `agent_routing` et `cloud_only_routing` : réussis après correction.

### Rollback

- Revenir au commit v2.281 et replacer la résolution imbriquée dans `run_agent`. Aucun schéma,
  réglage persistant ni contrat HTTP n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 62/62 étapes réussies; ESLint 0 erreur et
  37 avertissements historiques inchangés.
- Backend réel redémarré : version `2.282.0`, Ollama disponible.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, accueil Next.js inclus.
- `agent.py` passe de 1 424 à 1 310 lignes; la configuration reste disponible par façade.

## 2026-07-22 — v2.283.0 — État observable du Runner

### Constat et décision

- La boucle conservait ses compteurs, chronomètre, cause d'arrêt, traces, blocages et outils
  exécutés dans plus d'une dizaine de variables locales. Cela empêchait de tester l'évolution
  d'un run sans exécuter Ollama et favorisait les divergences entre provenance et apprentissage.
- Un `RunnerState` typé devient l'autorité unique de l'état mutable d'exécution.

### Implémentation

- Nouveau `backend/agent_runner.py` : `begin_step`, `record_tool`,
  `update_blocking_outcome`, `finish_reason` et `budget_usage`.
- `run_agent` utilise l'état pour son plafond temporel, les étapes consommées, les outils,
  l'auto-réparation des compétences, le golden path, les reçus Forge et la provenance Cortex.
- Le signal de chaîne longue est retourné une seule fois au neuvième appel; l'audit historique
  reste déclenché dans `agent.py`, tandis que la décision est testable sans effet externe.
- Nouveau `scripts/test_agent_runner.py` : temps, étapes, succès/échec, arguments expurgés de
  `confirmed`, signal unique, blocages Code/Test Forge, arrêt et métriques.

### Validation isolée réalisée avant versionnage

- Compilation de `agent_runner.py`, `agent.py` et du test : réussie.
- Tests `agent_runner`, `agent_execution` et `cortex` : réussis.

### Rollback

- Revenir au commit v2.282 et restaurer les compteurs locaux. Aucun schéma, réglage ni contrat
  HTTP n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 63/63 étapes réussies; ESLint 0 erreur et
  37 avertissements historiques inchangés.
- Backend réel redémarré : version `2.283.0`, Ollama disponible.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, accueil Next.js inclus.
- `agent.py` passe de 1 310 à 1 275 lignes; l'état reste accessible par façade.

## 2026-07-22 — v2.284.0 — Observabilité isolée du Runner

### Constat et décision

- Après chaque outil, `run_agent` écrivait directement vers quatre sous-systèmes distincts :
  audit JSONL, journal SQLite, preuve Mission OS et apprentissage du routeur. Ces effets
  best-effort encombraient la boucle et ne pouvaient pas être testés comme une frontière.
- Une observation typée unique est diffusée dans un module dédié. Chaque destination reste
  isolée afin qu'une panne d'observabilité ne fasse jamais échouer une action déjà exécutée.

### Implémentation

- Nouveau `backend/agent_observability.py` avec `ToolObservation`,
  `record_tool_observation` et `record_long_chain`.
- `run_agent` transmet le même résultat et la même durée aux consommateurs historiques. La
  durée est capturée après exécution et normalisation immédiate de l'outil; elle n'inclut plus
  la critique sensible ni les événements SSE ultérieurs.
- L'apprentissage du routeur reste limité aux résultats dictionnaires sans champ `error`.
- Nouveau `scripts/test_agent_observability.py` : contrats des quatre destinations, isolation
  d'une panne d'audit, absence d'apprentissage en erreur et bornage de l'alerte longue.

### Validation isolée réalisée avant versionnage

- Compilation de `agent_observability.py`, `agent.py` et du test : réussie.
- Tests `agent_observability`, `agent_runner` et `agent_execution` : réussis.

### Rollback

- Revenir au commit v2.283 et replacer les appels best-effort dans `run_agent`. Aucun schéma,
  réglage persistant ni contrat HTTP n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 64/64 étapes réussies; compilation de 135 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 29676, version `2.284.0`, Ollama disponible et 15 workers
  observés (12 actifs, 3 terminés au moment du health check).
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, accueil Next.js Turbopack inclus.
- `git diff --check` : aucun défaut de contenu; seuls les avertissements de normalisation LF
  vers CRLF propres au checkout Windows sont présents.
- `agent.py` passe de 1 275 à 1 240 lignes; les hooks historiques restent accessibles par
  façade et couverts par un test isolé.

## 2026-07-22 — v2.285.0 — Transport Ollama typé

### Constat et décision

- `run_agent` construisait deux payloads HTTP, gérait les timeouts, décodait directement le
  JSONL Ollama et traduisait les exceptions réseau. La boucle métier dépendait donc de détails
  de transport impossibles à tester sans la charger en entier.
- La frontière retenue est un adaptateur unique Ollama. Le protocole SSE reste volontairement
  dans le Runner : il appartient au contrat frontend, pas au transport du fournisseur LLM.

### Implémentation

- Nouveau `backend/agent_transport.py` : `OllamaChatRequest`, `OllamaStreamEvent`, fabrique de
  client, décodage JSONL, appel `/api/chat`, arrêt immédiat sur `done` et erreurs publiques.
- La redondance défensive du système est conservée : champ top-level `system` et premier
  message `role=system`. Le `keep_alive=30m` et les timeouts 300/120 secondes sont inchangés.
- Le client reste partagé pour toutes les étapes d'outils. La synthèse après épuisement du
  budget ouvre un client borné séparé et omet entièrement `tools`.
- Nouveau `scripts/test_agent_transport.py` avec transport HTTP simulé : URL, payload, ligne
  invalide, thinking, texte, outil, arrêt sur `done`, non-200 et projection des erreurs.

### Alternatives comparées

- Conserver HTTP dans `run_agent` limitait le changement mais maintenait le couplage et la
  duplication. Introduire maintenant une abstraction multi-fournisseur aurait ajouté une
  généralisation non requise. L'adaptateur Ollama dédié est le compromis le plus réversible.

### Validation isolée réalisée avant versionnage

- Compilation de `agent_transport.py`, `agent.py` et du test : réussie.
- Tests `agent_transport`, `agent_protocol` et `agent_runner` : réussis.
- `agent.py` ne contient plus d'import `httpx`, d'appel `/api/chat` ni de boucle `aiter_lines`.

### Rollback

- Revenir au commit v2.284 et restaurer les deux appels HTTP dans `run_agent`. Aucun schéma,
  réglage persistant ni format SSE n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 65/65 étapes réussies; compilation de 136 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 5800, version `2.285.0`, Ollama disponible et 15 workers
  observés (13 actifs, 2 terminés au moment du health check).
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, accueil Next.js Turbopack inclus.
- `agent.py` passe de 1 240 à 1 165 lignes; aucun détail HTTP/JSONL ne reste dans le Runner.

## 2026-07-22 — v2.286.0 — Domaine Tâches et Notes extrait

### Constat et décision

- `tools.py` dépassait 21 000 lignes et mélangeait implémentations métier, registre et contrats
  LLM. Les huit outils Tâches/Notes forment un domaine cohérent, à faible couplage et déjà
  couvert par les repositories de `database.py`.
- L'extraction progressive avec alias de façade est retenue. Une réécriture simultanée du
  registre ou des 344 schémas aurait augmenté inutilement le risque de perte fonctionnelle.

### Implémentation

- Nouveau `backend/tool_domains/productivity.py` : création, liste, mise à jour et suppression
  des tâches et notes, normalisation partagée des tags et cycle d'index Qdrant best-effort.
- `tools.py` importe le domaine et expose les huit noms historiques comme alias directs. Les
  entrées de `TOOLS_REGISTRY` référencent donc exactement les fonctions du domaine.
- La suppression reste soumise à `confirmed`; aucune mutation n'a lieu lors de la première
  réponse `requiresConfirmation`.
- Durcissement borné : un statut de tâche non textuel renvoie une erreur structurée au lieu
  de lever sur `.lower()` avant le bloc historique de gestion d'erreur.
- Nouveau `scripts/test_tool_domain_productivity.py` : tags, filtres, alias, confirmations,
  mutations, indexation et identité des huit entrées, avec contrôle strict 344/344.

### Validation isolée réalisée avant versionnage

- Compilation du domaine, de `tools.py` et du test : réussie.
- Tests Productivité, Quiz et Base IT : réussis.
- `scripts/check_architecture.py` : 344 outils, 346 routes, 40 pages.
- `tools.py` passe de 21 079 à 20 927 lignes.

### Rollback

- Revenir au commit v2.285 et replacer les huit fonctions dans `tools.py`. Aucun schéma SQLite,
  contrat d'outil, nom public ni format de résultat n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 66/66 étapes réussies; compilation de 137 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 30384, version `2.286.0`, Ollama disponible et 15 workers
  observés (13 actifs, 2 terminés au moment du health check).
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, dont les contrats projets,
  tâches et notes ainsi que l'accueil Next.js Turbopack.

## 2026-07-22 — v2.287.0 — Domaine Mémoire extrait

### Constat et décision

- Les outils mémoire combinaient dans `tools.py` dédoublonnage, persistance SQLite, Memory
  Mesh et Qdrant. Leur cohérence mérite une frontière testable indépendamment du registre.
- Le domaine est extrait sans déplacer les spécifications LLM : la façade reste stable pendant
  la migration progressive et les consommateurs historiques ne changent pas d'import.

### Implémentation

- Nouveau `backend/tool_domains/memory.py` : sauvegarde dédoublonnée, liste, suppression
  confirmée, recherche sémantique et repli textuel.
- Les effets Memory Mesh et Qdrant sont séparés en adaptateurs best-effort; leur panne ne fait
  pas perdre une écriture SQLite déjà réussie, conformément au comportement historique.
- `tools.py` expose les quatre noms historiques par alias direct et conserve les quatre entrées
  de `TOOLS_REGISTRY` et `TOOLS_SPEC`.
- Durcissement borné : contenu/catégorie/identifiant sont normalisés et une limite de recherche
  non numérique produit une erreur exploitable, bornée entre 1 et 20.
- Nouveau `scripts/test_tool_domain_memory.py` : doublon, enrichissement, création, Mesh,
  index, confirmation, suppression, recherche sémantique, panne Qdrant et repli SQLite.

### Validation isolée réalisée avant versionnage

- Compilation du domaine, de `tools.py` et du test : réussie.
- Tests Mémoire et Productivité : réussis.
- `scripts/check_architecture.py` : 344 outils, 346 routes, 40 pages.
- `tools.py` passe de 20 927 à 20 801 lignes.

### Rollback

- Revenir au commit v2.286 et replacer les quatre fonctions dans `tools.py`. Aucun schéma,
  contrat d'outil, nom public ni format de résultat n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 67/67 étapes réussies; compilation de 138 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 29596, version `2.287.0`, Ollama disponible et 15 workers
  observés (12 actifs, 3 terminés au moment du health check).
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, dont mémoires, paramètres,
  sauvegardes et accueil Next.js Turbopack.

## 2026-07-22 — v2.288.0 — Frontière SSH unique dans api/ssh.py

### Constat et décision

- `main.py` conservait encore les modèles et douze fonctions SSH marqués « migrés vers
  api/ssh.py ». Ils n'avaient plus aucun décorateur FastAPI et aucune référence dans le dépôt,
  mais dupliquaient CRUD, test, commande, SSE, PTY WebSocket et SFTP.
- Les garder créait deux sources de vérité dont une seule était réellement exécutée. Après
  vérification des routes actives, les copies mortes sont supprimées plutôt que maintenues.

### Implémentation

- Retrait de `SSHConnectionCreate`, `SSHConnectionUpdate`, `SSHCommandRequest` et des copies
  de fonctions SSH dans `main.py`; retrait des imports `io`, `security`, `WebSocket` et
  `WebSocketDisconnect` devenus inutilisés dans ce fichier.
- Aucun code de `api/ssh.py` n'est modifié : garde de commande, clé multi-format, streaming,
  PTY et transferts restent inchangés.
- Nouveau `scripts/test_ssh_router_boundary.py` : les 11 contrats HTTP attendus et le chemin
  WebSocket doivent exister et chaque endpoint doit appartenir au module `api.ssh`.

### Validation isolée réalisée avant versionnage

- Recherche repo-wide : aucune référence externe aux copies supprimées.
- Compilation de `main.py`, `api/ssh.py` et du test : réussie.
- Test de frontière SSH : 11 contrats HTTP, WebSocket et propriétaire de module réussis.
- `scripts/check_architecture.py` : 344 outils, 346 routes, 40 pages.
- `main.py` passe de 5 018 à 4 687 lignes.

### Rollback

- Revenir au commit v2.287 réintroduit uniquement les copies mortes; le routeur actif et les
  données ne changent pas. Aucun schéma, secret, connexion SSH ni contrat HTTP n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 68/68 étapes réussies; compilation de 138 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 34016, version `2.288.0`, Ollama disponible et 15 workers
  observés (12 actifs, 3 terminés au moment du health check).
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, dont les connexions SSH masquées
  et l'accueil Next.js Turbopack.

## 2026-07-22 — v2.289.0 — Frontière des comptes e-mail

### Constat et décision

- `main.py` mélangeait la configuration multi-comptes avec les opérations de boîte IMAP/SMTP.
  Les sept routes de compte forment une frontière cohérente et peuvent être extraites sans
  toucher au comportement de lecture, envoi, automatisation ou pièces jointes.
- Un service partagé est retenu afin que les routes extraites et les opérations restantes
  utilisent la même résolution OAuth/mot de passe, sans dépendance circulaire avec `main.py`.

### Implémentation

- Nouveau `backend/email_account_service.py` : résolution, liste publique, upsert mot de passe
  applicatif, retrait et projection de configuration expurgée.
- Nouveau `backend/api/email_accounts.py` : providers, GET/POST config, GET/POST/DELETE comptes
  et test de connexion exécuté hors de la boucle asyncio.
- `main.py` monte le routeur et importe seulement `get_resolved`/`list_resolved` pour les
  opérations IMAP encore présentes.
- Nouveau `scripts/test_email_accounts_boundary.py` : masquage des secrets, défaut
  multi-comptes, auth_type et propriété exacte des sept routes.

### Validation isolée réalisée avant versionnage

- Compilation du service, du routeur, de `main.py` et du test : réussie.
- Tests frontière comptes et orchestrateur e-mail : réussis.
- `scripts/check_architecture.py` : 344 outils, 346 routes, 40 pages.
- `main.py` passe de 4 687 à 4 593 lignes.

### Rollback

- Revenir au commit v2.288 et replacer les sept routes dans `main.py`. Aucun compte, jeton,
  schéma, fournisseur, contrat HTTP ni mode d'authentification n'est supprimé.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 69/69 étapes réussies; compilation de 140 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 31724, version `2.289.0`, Ollama disponible et 15 workers
  observés (13 actifs, 2 terminés au moment du health check).
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, dont connexions masquées,
  orchestrateur e-mail et accueil Next.js Turbopack.

## 2026-07-22 — v2.290.0 — Frontière de la boîte e-mail

### Constat et décision

- Après les comptes, `main.py` portait encore neuf opérations IMAP/SMTP cohérentes et leurs
  détails d'exécution bloquante. Elles partageaient toutes la résolution de compte désormais
  centralisée et pouvaient être extraites sans toucher à l'automatisation IA.
- Un routeur de boîte séparé est retenu; comptes, boîte et automatisation restent trois
  responsabilités distinctes au lieu d'un unique module e-mail massif.

### Implémentation

- Nouveau `backend/api/email_mailbox.py` : boîte simple/unifiée, lecture, recherche, dossiers,
  envoi, suppression, marquage, déplacement et pièce jointe.
- La résolution OAuth ou mot de passe passe exclusivement par `email_account_service`; les
  appels IMAP/SMTP bloquants restent exécutés dans l'executor asyncio.
- La journalisation SQLite de `email_send` et le nom de compte `_account` dans les résultats
  unifiés sont préservés.
- Nouveau `scripts/test_email_mailbox_boundary.py` : agrégation multi-boîtes, envoi/audit,
  pièce jointe UTF-8, refus sans compte et propriété exacte des neuf routes.

### Validation isolée réalisée avant versionnage

- Compilation du routeur, de `main.py` et du test : réussie.
- Tests boîte, comptes et orchestrateur e-mail : réussis sans connexion externe.
- `scripts/check_architecture.py` : 344 outils, 346 routes, 40 pages.
- `main.py` passe de 4 593 à 4 390 lignes.

### Rollback

- Revenir au commit v2.289 et replacer les neuf routes dans `main.py`. Aucun compte, message,
  pièce jointe, schéma, contrat HTTP ou mode d'authentification n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 70/70 étapes réussies; compilation de 141 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 31992, version `2.290.0`, Ollama disponible et 15 workers
  observés (12 actifs, 3 terminés au moment du health check).
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, dont orchestrateur e-mail,
  connexions masquées et accueil Next.js Turbopack.

## 2026-07-22 — v2.292.0 — Frontière IA et automatisation e-mail

### Constat et décision

- Les dernières routes e-mail de `main.py` combinaient appels IA, configuration du scheduler,
  drafts et outbox. Cette responsabilité est distincte des comptes, de la boîte et des
  préférences déjà extraits.
- Le routeur dédié conserve la délégation aux outils existants : aucune seconde implémentation
  d'envoi, de résumé ou d'orchestration n'est introduite.

### Implémentation

- Nouveau `backend/api/email_automation.py` : 13 routes et trois modèles Pydantic.
- Le premier passage `scheduler_enabled=false` vers `true` reste refusé en HTTP 409 sans
  `scheduler_confirmed`; ce champ de confirmation est exclu des données persistées.
- Les limites restent 2–1440 minutes, 1–100 réponses et 1–1440 minutes de délai. Les listes
  anciennes sérialisées en JSON restent acceptées défensivement.
- Nouveau `scripts/test_email_automation_boundary.py` : confirmation, bornes, profils,
  arguments outils, dry-run, outbox et propriété exacte des 13 routes.

### Validation isolée réalisée avant versionnage

- Compilation du routeur, de `main.py` et du test : réussie.
- Tests frontière et orchestrateur e-mail : réussis sans envoi ni accès réseau.
- `scripts/check_architecture.py` : 344 outils, 346 routes, 40 pages.
- `main.py` passe de 4 287 à 4 108 lignes.

### Rollback

- Revenir au commit v2.291 et replacer les 13 routes dans `main.py`. Aucun compte, profil,
  draft, envoi différé, schéma, contrat HTTP ou garde de confirmation n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 72/72 étapes réussies; compilation de 143 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 3372, version `2.292.0`, Ollama disponible et 15 workers
  observés (12 actifs, 3 terminés au moment du health check).
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, dont orchestrateur e-mail,
  planification et accueil Next.js Turbopack.

## 2026-07-22 — v2.293.0 — Frontière vidéo distante Replicate

### Constat et décision

- `main.py` contenait encore le catalogue Replicate et les six routes distantes au milieu des
  traitements vidéo locaux. Ce bloc possède une dépendance et un cycle de vie distincts :
  jeton Replicate, appel HTTP distant, suivi SSE et import du résultat.
- Deux choix ont été comparés : déplacer tout le domaine vidéo en une fois, ou extraire d'abord
  la frontière distante. L'extraction progressive est retenue : elle limite le changement à
  six contrats HTTP et laisse intacts ffmpeg, les fichiers locaux et la génération IA locale.

### Implémentation

- Nouveau `backend/api/video_remote.py` : catalogue texte/image, génération Replicate,
  suivi SSE, annulation et téléchargement d'une URL générée.
- Le jeton est toujours obtenu par `credentials_manager`; aucun secret ni nouvelle méthode de
  connexion n'est introduit. Les appels restent délégués à `video_manager.py`.
- Nouveau `scripts/test_video_remote_boundary.py` : fusion des paramètres, upload image,
  refus sans jeton et propriété exacte des six routes.
- La nouvelle frontière est ajoutée aux invariants d'architecture et à `check_marvin --quick`.

### Validation isolée réalisée avant versionnage

- Compilation de `api/video_remote.py`, `main.py` et du test : réussie.
- Test de frontière : six routes, paramètres texte/image et absence de jeton validés.
- `scripts/check_architecture.py` : 344 outils, 346 routes, 40 pages.
- `main.py` passe de 4 108 à 3 794 lignes sans suppression de route.

### Rollback

- Revenir au commit v2.292 et replacer les six routes dans `main.py`. Aucun modèle vidéo,
  fichier local, secret, contrat HTTP ou format de réponse n'est migré.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 73/73 étapes réussies; compilation de 144 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 28380, version `2.293.0`, Ollama disponible et 15 workers
  observés (13 actifs, 2 terminés au moment du health check).
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, dont Code Workspace,
  orchestrateur e-mail et accueil Next.js Turbopack.

## 2026-07-22 — v2.297.0 — Transport SSH partagé

### Constat et décision

- Le routeur SSH appelait `_ssh_connect`, helper privé de `tools.py`. Cette dépendance inversée
  empêchait d'extraire proprement le domaine SSH et liait l'API au registre complet des outils.
- Un transport partagé est retenu plutôt qu'une nouvelle copie : une seule implémentation reste
  responsable des formats de clés, des paramètres Paramiko et des timeouts.

### Implémentation

- Nouveau `backend/ssh_transport.py` avec `load_private_key` et `connect`.
- Les sept appels de connexion du routeur utilisent directement ce transport. `tools.py`
  conserve ses deux noms privés comme alias de compatibilité, sans duplication.
- Nouveau `scripts/test_ssh_transport.py` : ordre des formats de clé, mot de passe, paramètres,
  identité des alias et absence de dépendance privée dans le routeur.

### Validation isolée réalisée avant versionnage

- Compilation du transport, du routeur, de `tools.py` et du test : réussie.
- Tests transport et frontière SSH : réussis; 11 contrats HTTP/WebSocket conservés.
- `scripts/check_architecture.py` : 344 outils, 346 routes, 40 pages.

### Rollback

- Revenir au commit v2.296 et replacer les deux helpers dans `tools.py`. Aucune connexion,
  clé, empreinte, donnée utilisateur ou route n'est migrée.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 77/77 étapes réussies; compilation de 149 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 6824, version `2.297.0`, Ollama disponible et 15 workers.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, dont SSH, Code Workspace et
  accueil Next.js Turbopack.

## 2026-07-22 — v2.298.0 — Domaine d'outils SSH

### Constat et décision

- Après extraction du transport, neuf outils SSH restaient dans `tools.py` et le routeur
  dépendait du registre pour parcourir un dossier et obtenir le diagnostic serveur.
- Un domaine unique est retenu afin que l'API et le registre partagent les mêmes garde-fous,
  confirmations, résolutions de cibles et transferts, sans appel circulaire.

### Implémentation et validation isolée

- Nouveau `tool_domains/ssh.py`; `tools.py` injecte chemins, format de taille et dossier home,
  puis réexporte directement les neuf fonctions.
- `api/ssh.py` appelle le domaine pour browse/info et n'importe plus `tools.py`.
- Nouveau test : secrets, port, confirmation, garde, exécution simulée, fermeture du client,
  identité 344/344 et absence du cycle API. Tests transport, routeur et architecture réussis.
- `tools.py` passe de 20 555 à 20 197 lignes; 346 routes et 344 outils sont conservés.

### Rollback

- Revenir au commit v2.297. Aucune connexion, clé, commande, fichier ou donnée n'est migrée.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 78/78 étapes réussies; compilation de 151 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 19244, version `2.298.0`, Ollama disponible et 15 workers.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.

## 2026-07-22 — v2.296.0 — Domaine d'outils Média

### Constat et décision

- Les 17 outils vidéo/GIF/audio formaient un adaptateur homogène vers `video_manager.py`, mais
  restaient noyés dans `tools.py`. Leur seule dépendance transversale significative était le
  résolveur portable de chemins Windows.
- Deux approches ont été comparées : déplacer aussi le résolveur global, ce qui toucherait de
  nombreux domaines, ou l'injecter dans le module média. L'injection bornée est retenue pour
  conserver le comportement exact sans élargir cette tranche.

### Implémentation

- Nouveau `backend/tool_domains/media.py` : onze actions vidéo/GIF, six actions audio, exécution
  bloquante dans l'executor et helpers communs pour chemins et sorties.
- `tools.py` configure le résolveur historique puis réexporte directement les 17 fonctions;
  le registre et `TOOLS_SPEC` ne changent pas.
- Nouveau `scripts/test_tool_domain_media.py` : chemin requis, métadonnées, trim, capture bornée,
  fusion audio, conversions et identité stricte 344/344.

### Validation isolée réalisée avant versionnage

- Compilation du domaine, de `tools.py` et du test : réussie.
- Test média : vidéo, GIF, audio, chemins et 17 identités validés sans appel ffmpeg réel.
- `scripts/check_architecture.py` : 344 outils, 346 routes, 40 pages.
- `tools.py` passe de 20 801 à 20 581 lignes.

### Rollback

- Revenir au commit v2.295 et replacer les 17 fonctions dans `tools.py`. Aucun fichier média,
  schéma d'outil, chemin utilisateur ou contrat de résultat ne subit de migration.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 76/76 étapes réussies; compilation de 147 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 33264, version `2.296.0`, Ollama disponible et 15 workers
  observés (13 actifs, 2 terminés au moment du health check).
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, dont Code Workspace,
  orchestrateur e-mail et accueil Next.js Turbopack.

## 2026-07-22 — v2.295.0 — Génération vidéo IA locale

### Constat et décision

- La capacité GPU, les modèles Diffusers, les deux générations SSE et leur annulation étaient
  encore couplés au composition root. L'amélioration de prompt utilise la même UX vidéo et
  reste dans cette frontière, tout en déléguant l'inférence à Ollama.
- Cette extraction achève le découpage du domaine vidéo en trois responsabilités indépendantes :
  fournisseur distant, montage/fichiers locaux et génération IA locale.

### Implémentation

- Nouveau `backend/api/video_local.py` avec les cinq routes historiques, les modèles Pydantic,
  le contrôle de capacité et les raisons de mode dégradé.
- Le SSE, les paramètres Diffusers, l'annulation coopérative et le choix Ollama existants sont
  conservés. Aucun modèle n'est téléchargé ou chargé par les tests.
- Correction connexe : le fichier temporaire de l'image est maintenant nettoyé par un `finally`
  englobant aussi le refus pour capacité désactivée.
- Nouveau `scripts/test_video_local_boundary.py` : matériel/réglage, erreur SSE, nettoyage,
  annulation, prompt vide et propriété exacte des cinq routes.

### Validation isolée réalisée avant versionnage

- Compilation du routeur, de `main.py` et du test : réussie.
- Test de frontière : capacité, SSE, nettoyage, annulation et cinq routes validés.
- `scripts/check_architecture.py` : 344 outils, 346 routes, 40 pages.
- `main.py` passe de 3 544 à 3 375 lignes.

### Rollback

- Revenir au commit v2.294 et replacer les cinq routes dans `main.py`. Les modèles locaux,
  réglages de performance, artefacts vidéo et formats SSE ne subissent aucune migration.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 75/75 étapes réussies; compilation de 146 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 28048, version `2.295.0`, Ollama disponible et 15 workers
  observés (13 actifs, 2 terminés au moment du health check).
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, dont Code Workspace,
  orchestrateur e-mail et accueil Next.js Turbopack.

## 2026-07-22 — v2.294.0 — Création et montage vidéo locaux

### Constat et décision

- Les routes de diaporama, texte animé, fichiers et édition ffmpeg formaient une frontière
  locale déterministe distincte de Replicate et des modèles Diffusers.
- Extraire ce bloc avant la génération IA locale réduit le risque : les contrats de fichiers
  et ffmpeg peuvent être testés sans charger de modèle ni utiliser le réseau.

### Implémentation

- Nouveau `backend/api/video_editing.py` avec les six routes historiques et l'exécution des
  traitements bloquants dans l'executor asyncio.
- La résolution des fichiers accepte les noms simples existants mais refuse désormais toute
  traversée ou sortie du répertoire retourné par `video_manager.get_video_dir()`.
- Nouveau `scripts/test_video_editing_boundary.py` : animation de texte, résultat de capture,
  plafond de durée, parsing de région, confinement de chemin et propriété exacte des routes.

### Validation isolée réalisée avant versionnage

- Compilation du routeur, de `main.py` et du test : réussie.
- Test de frontière : création, stockage sûr, capture ffmpeg et six routes validés.
- `scripts/check_architecture.py` : 344 outils, 346 routes, 40 pages.
- `main.py` passe de 3 794 à 3 544 lignes.

### Rollback

- Revenir au commit v2.293 et replacer les six routes dans `main.py`. Les fichiers générés,
  leurs formats, ffmpeg et les signatures HTTP ne subissent aucune migration.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 74/74 étapes réussies; compilation de 145 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 17776, version `2.294.0`, Ollama disponible et 15 workers
  observés (12 actifs, 3 terminés au moment du health check).
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, dont Code Workspace,
  orchestrateur e-mail et accueil Next.js Turbopack.

## 2026-07-22 — v2.291.0 — Frontière des préférences e-mail

### Constat et décision

- Signatures, modèles, surveillance, alertes et règles formaient un bloc persistant cohérent
  encore mélangé au composition root. Ces routes ne réalisent directement aucun accès IMAP ou
  SMTP et peuvent évoluer indépendamment de la boîte et de l'automatisation.
- Elles sont regroupées dans un routeur dédié; les actions « exécuter maintenant » continuent
  d'appeler le registre d'outils, afin de ne pas dupliquer leurs garde-fous métier.

### Implémentation

- Nouveau `backend/api/email_preferences.py` avec décodage défensif des anciens réglages JSON,
  signatures par compte, remplacement de modèle homonyme et plafond historique de 50.
- Surveillance, alertes et règles conservent les mêmes clés SQLite et formats de réponse.
- Nouveau `scripts/test_email_preferences_boundary.py` : compatibilité JSON, signature,
  remplacement de modèle, délégation aux outils et propriété exacte des 13 routes.

### Validation isolée réalisée avant versionnage

- Compilation du routeur, de `main.py` et du test : réussie.
- Tests préférences et boîte e-mail : réussis sans action externe.
- `scripts/check_architecture.py` : 344 outils, 346 routes, 40 pages.
- `main.py` passe de 4 390 à 4 287 lignes.

### Rollback

- Revenir au commit v2.290 et replacer les 13 routes dans `main.py`. Aucun réglage, message,
  compte, règle, contrat HTTP ou outil n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 71/71 étapes réussies; compilation de 142 fichiers
  Python, ESLint 0 erreur et 37 avertissements historiques inchangés.
- Backend réel redémarré : PID 20824, version `2.291.0`, Ollama disponible et 15 workers
  observés (12 actifs, 3 terminés au moment du health check).
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis, dont orchestrateur e-mail,
  connexions masquées et accueil Next.js Turbopack.
## 2026-07-26 — v2.300.0 — Repository transactionnel des workflows

### Constat et décision

- Les définitions de workflows et leurs exécutions restaient dans `database.py`, alors que
  l'API et le moteur cron forment un domaine métier cohérent et testable séparément.
- Deux options ont été comparées : extraire uniquement le CRUD des définitions, ou déplacer
  ensemble définitions et exécutions. La seconde est retenue pour préserver dans une même
  frontière la mise à jour du compteur, l'historique et la suppression atomique.
- Le schéma SQLite, les noms de fonctions de la façade `database.py` et les formats retournés
  restent compatibles. Aucune route, aucun outil et aucune donnée existante n'est supprimé.

### Implémentation

- Nouveau `backend/repositories/workflows.py` avec `WorkflowRepository` injectable et aliases
  historiques pour `database.py`.
- Création, liste, lecture, mise à jour, suppression, création et terminaison d'exécution
  utilisent toutes la fabrique transactionnelle `db()`.
- Les anciens champs JSON illisibles se replient sur `[]`; la limite d'historique est bornée
  entre 1 et 200; la suppression des exécutions et du workflow est atomique.
- Nouveau `scripts/test_workflow_repository.py`, intégré à `check_marvin --quick`.

### Validation isolée réalisée avant versionnage

- Compilation Python ciblée : réussie.
- CRUD, JSON, exécutions, bornes, suppression et rollback : réussis sur SQLite temporaire.
- Hygiène SQLite : aucune connexion directe hors de la fabrique.
- Architecture : 344 outils, 346 routes et 40 pages.

### Rollback

- Revenir au commit v2.299 et replacer les fonctions de workflows dans `database.py`.
  Le schéma SQLite n'a subi aucune migration et les données restent directement compatibles.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 80/80 étapes réussies; compilation de 151 fichiers
  Python, cohérence 344/344 outils et ESLint sans erreur (37 avertissements historiques).
- Backend réel redémarré : processus lancé PID 28944, version `2.300.0`, Ollama disponible
  et 15 workers observés.
- Le premier smoke test a correctement identifié que Next.js n'était pas démarré : 22/28.
  Le frontend normal a été lancé avec `npm run dev` sous Turbopack, HTTP 200 confirmé, puis
  `scripts/smoke_test_api.py` a validé 28/28 contrats, dont workflows et Code Workspace.

## 2026-07-26 — v2.301.0 — Finalisation commune du Runner

### Constat et décision

- `run_agent` appliquait deux fois la même séquence : scanner la réponse, déclencher la revue
  indépendante, arbitrer un désaccord avec le Council puis émettre les événements SSE.
- Conserver deux copies exposait les sorties normales et par budget à une divergence future.
  Une fonction pure sur les effets externes, avec callbacks injectés, est retenue plutôt
  qu'une réécriture globale de la boucle agentique.

### Implémentation

- Nouveau `backend/agent_finalization.py` avec résultat typé `FinalizedAnswer`.
- La séquence sécurité, critique, Council et ajout de contenu est centralisée; la persistance,
  la provenance et le streaming restent sous le contrôle explicite du Runner.
- Les deux sorties de `agent.py` consomment le même composant sans modifier le choix du modèle,
  le mode de confidentialité, les critères Cortex ou l'ordre des événements.
- Nouveau `scripts/test_agent_finalization.py`, intégré à `check_marvin --quick`.

### Validation isolée réalisée avant versionnage

- Compilation de `agent.py`, du nouveau module et du test : réussie.
- Sécurité, critique forcée, Council, ordre des cinq événements et chemin sans revue : réussis.
- Régressions `agent_review` et `agent_runner` : réussies.
- Architecture : 344 outils, 346 routes et 40 pages.

### Rollback

- Revenir au commit v2.300 et replacer les deux séquences de finalisation dans `agent.py`.
  Aucun contrat SSE, schéma, outil, route, modèle ou donnée persistée n'est migré.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 81/81 étapes réussies; compilation de 152 fichiers
  Python, cohérence 344/344 outils et ESLint sans erreur.
- Backend réel redémarré : processus lancé PID 13432, version `2.301.0`, Ollama disponible,
  344 outils et 15 workers observés.
- `scripts/smoke_test_api.py` : 28/28 contrats réussis avec le frontend Turbopack actif.

## 2026-07-27 — v2.312.0 — Finalisation commune du tour

### Constat et décision

- Les sorties normale et par épuisement de budget dupliquaient revue, persistance, issue de
  compétence, recette Cortex, provenance et événement `done`.
- Cette duplication pouvait faire diverger l'ordre des événements ou oublier un effet terminal.

### Implémentation

- Nouveau `backend/agent_turn_completion.py` avec `TurnCompletion`.
- Revue et éventuel Council précèdent toujours la persistance finale.
- L'issue de compétence précède la provenance, puis `done` termine le flux.
- La recette Cortex reste best-effort et la provenance utilise la cause d'arrêt exacte.
- L'apprentissage durable reste activé sur une réponse normale et désactivé sur la synthèse
  par budget, afin de ne pas mémoriser une réponse déclarée incomplète.
- Nouveau test déterministe intégré à `check_marvin --quick`.
- `agent.py` passe de 619 à 560 lignes.

### Validation isolée réalisée avant versionnage

- Compilation du module, du Runner et du test : réussie.
- Ordre, Council, apprentissage, skill, recette et provenance : réussis.
- Régressions Finalization, Skill Outcome et Learning : réussies.
- Architecture : 344 outils, 346 routes, 40 pages et 64 outils encadrés.

### Rollback

- Revenir au commit v2.311 et restaurer les deux séquences terminales dans `agent.py`.
  Aucun événement SSE, message persistant, critique ou provenance ne change.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 94/94 étapes réussies en 114,6 secondes.
- Backend compilé : 165 fichiers Python.
- Frontend : 0 erreur ESLint ; 37 avertissements historiques, hors périmètre de cette tranche.
- Redémarrage réel : `/api/health` expose `2.312.0`, Ollama disponible, 344/344 outils et
  15 workers supervisés.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.

## 2026-07-27 — v2.311.0 — Lot d'outils observé et persistant

### Constat et décision

- `run_agent` exécutait encore chaque appel, diffusait les événements, mettait à jour les
  preuves et persistait manuellement l'étape dans un bloc d'environ 160 lignes.
- Cette séquence doit rester strictement ordonnée et testable sans modèle ni véritable outil.

### Implémentation et améliorations

- Nouveau `backend/agent_tool_batch.py`.
- Identifiant, préparation, contexte interne, dispatch, durée et post-validation sont isolés.
- `tool_start` reste émis avant exécution et `tool_end` après post-validation.
- Les gates Forge mettent toujours à jour le tampon bloquant avant le tour suivant.
- Observation, état du Runner, chaîne longue, contexte Ollama et persistance sont conservés.
- Une exception de l'observateur ou de l'alerte de chaîne longue est maintenant absorbée à
  cette frontière, même avec une implémentation injectée non conforme.
- Nouveau test de lot intégré à `check_marvin --quick`.
- `agent.py` passe de 727 à 619 lignes.

### Validation isolée réalisée avant versionnage

- Compilation du module, du Runner et des tests : réussie.
- Dispatch, événements, durée, Forge, preuve, état, contexte et persistance : réussis.
- Exception réelle de l'observateur après exécution : absorbée, résultat conservé.
- Régressions Model Step, Dispatch et Observability : réussies.
- Architecture : 344 outils, 346 routes, 40 pages et 64 outils encadrés.

### Rollback

- Revenir au commit v2.310 et replacer la séquence dans `agent.py`.
  Aucun événement SSE, reçu, argument interne, résultat complet ou message persistant ne change.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 93/93 étapes réussies en 113,7 secondes.
- Backend compilé : 164 fichiers Python.
- Frontend : 0 erreur ESLint ; 37 avertissements historiques, hors périmètre de cette tranche.
- Redémarrage réel : `/api/health` expose `2.311.0`, Ollama disponible, 344/344 outils et
  15 workers supervisés.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.

## 2026-07-27 — v2.310.0 — Itération modèle typée

### Constat et décision

- La boucle lisait directement le stream Ollama, concaténait le texte, projetait les événements,
  récupérait les appels textuels et injectait les outils contractuels.
- L'audit a aussi détecté un défaut runtime : `uuid` avait été retiré alors que la création
  des identifiants `toolCallId` l'utilisait encore. La compilation seule ne détectait pas ce nom.

### Implémentation et amélioration

- Nouveau `backend/agent_model_step.py` avec `ModelStepResult` et `PreparedModelStep`.
- `stream_model_step` projette `thinking`/`text`, respecte le masquage Forge et collecte les
  appels natifs sans dépendre du SSE.
- `prepare_model_step` récupère les appels textuels puis matérialise les outils requis.
- L'import `uuid` est restauré et exercé par le test runtime.
- Nouveau test déterministe intégré à `check_marvin --quick`.
- La façade `run_agent` conserve l'erreur transport historique et l'ordre exact des événements.

### Validation isolée réalisée avant versionnage

- Compilation du module, du Runner et du test : réussie.
- Streaming, masquage, récupération, outils requis et génération UUID : réussis.
- Régressions Transport et Required Tools : réussies.
- Architecture : 344 outils, 346 routes, 40 pages et 64 outils encadrés.

### Rollback

- Revenir au commit v2.309 et replacer la lecture du stream dans `agent.py`, en conservant
  impérativement l'import `uuid`. Aucun contrat Ollama, SSE ou outil n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 92/92 étapes réussies en 113,3 secondes.
- Backend compilé : 163 fichiers Python.
- Frontend : 0 erreur ESLint ; 37 avertissements historiques, hors périmètre de cette tranche.
- Redémarrage réel : `/api/health` expose `2.310.0`, Ollama disponible, 344/344 outils et
  15 workers supervisés.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.

## 2026-07-27 — v2.309.0 — Enrichissements concurrents et contexte Skill

### Constat et décision

- Le rappel sémantique, le matching de compétence et le filtrage d'outils étaient lancés dans
  `run_agent`, puis attendus à des endroits différents sans contrat d'annulation commun.
- Une sortie anticipée pendant l'escalade Cloud d'une skill pouvait laisser des tâches
  préparatoires actives; une compétence Markdown incomplète pouvait lever une exception.

### Implémentation et améliorations

- Nouveau `backend/agent_enrichment.py` avec `EnrichmentTasks`.
- Les trois tâches restent concurrentes; chaque panne indépendante se replie sur vide.
- `cancel_pending()` annule et attend toutes les tâches encore actives avant une sortie Cloud.
- L'injection du rappel sémantique et l'assemblage sans doublon du catalogue sont testables.
- Nouveau `backend/agent_skill_context.py` : validation des champs, méthode agentique, golden
  path borné à huit étapes et ressources best-effort.
- Une compétence invalide est ignorée proprement au lieu de casser le tour.
- Deux tests déterministes sont intégrés à `check_marvin --quick`.
- `agent.py` passe de 788 à 726 lignes.

### Validation isolée réalisée avant versionnage

- Compilation des deux modules, du Runner et des tests : réussie.
- Concurrence, replis, annulation, mémoire et catalogue : réussis.
- Méthode Skill, golden path, ressources et Markdown invalide : réussis.
- Régressions sélection d'outils et Ultra cloud-only : réussies.
- Architecture : 344 outils, 346 routes, 40 pages et 64 outils encadrés.

### Rollback

- Revenir au commit v2.308 et replacer les enrichissements et le prompt Skill dans `agent.py`.
  Aucun format de compétence, outil, événement SSE ou politique Cloud n'est supprimé.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 91/91 étapes réussies en 109,7 secondes.
- Backend compilé : 162 fichiers Python.
- Frontend : 0 erreur ESLint ; 37 avertissements historiques, hors périmètre de cette tranche.
- Redémarrage réel : `/api/health` expose `2.309.0`, Ollama disponible, 344/344 outils et
  15 workers supervisés.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.

## 2026-07-27 — v2.308.0 — Contexte déterministe du tour

### Constat et décision

- `run_agent` préparait directement la fenêtre d'historique, les chemins réels, les mémoires,
  permissions, instructions de projet, identité documentaire et politique d'outils.
- Ces données sont un contexte d'entrée cohésif, antérieur aux skills et à la boucle LLM.

### Implémentation

- Nouveau `backend/agent_turn_context.py` avec `PreparedAgentContext`.
- La profondeur d'historique conserve le réglage runtime et son repli.
- Une profondeur nulle/négative est ramenée à un message afin de ne jamais retirer la demande
  utilisateur courante; un retour de mémoire non conforme se replie sur une liste vide.
- Le premier tour injecte toujours `pc_get_real_paths` juste avant la demande utilisateur.
- Le mode réponse directe, les outils imposés et le mode Cortex conseil seulement conservent
  leurs politiques exactes.
- Projet et identité documentaire restent best-effort, sans rendre le tour indisponible.
- Nouveau test déterministe intégré à `check_marvin --quick`.
- `agent.py` passe de 867 à 788 lignes après retrait des commentaires devenus orphelins.

### Validation isolée réalisée avant versionnage

- Compilation du module, du Runner et du test : réussie.
- Historique, chemins, permissions, projet, identité et politique d'outils : réussis.
- Régressions Prompt, Session et Planning : réussies.
- Architecture : 344 outils, 346 routes, 40 pages et 64 outils encadrés.

### Rollback

- Revenir au commit v2.307 et replacer la préparation du contexte dans `agent.py`.
  Aucun message Ollama, prompt, route, outil ou réglage persistant n'est supprimé.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 89/89 étapes réussies en 116,8 secondes après
  l'amélioration du cas limite d'historique.
- Backend compilé : 160 fichiers Python.
- Frontend : 0 erreur ESLint ; 37 avertissements historiques, hors périmètre de cette tranche.
- Redémarrage réel du code final : `/api/health` expose `2.308.0`, Ollama disponible,
  344/344 outils et 15 workers supervisés.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.

## 2026-07-27 — v2.307.0 — Effets post-réponse du Runner

### Constat et décision

- L'escalade Council et l'apprentissage durable restaient définis comme closures dans
  `run_agent`, alors qu'ils sont des effets post-réponse aux politiques indépendantes.
- Leur extraction précède la future extraction de la préparation du tour et évite de déplacer
  simultanément mémoire, skills, routage Cloud et boucle d'outils.

### Implémentation

- Nouveau `backend/agent_council_escalation.py` : Council exige un désaccord réel, un axe
  `review` explicitement demandé et la politique `council_if_disagreement`.
- Les preuves transmises restent bornées à 5 000 caractères de réponse et 1 800 de critique.
- Nouveau `backend/agent_learning.py` : choix `resident`/`dedicated`, professeur injectable,
  tâche conservée dans le registre anti-GC et repli résident si le réglage est indisponible.
- Deux tests déterministes sont intégrés à `check_marvin --quick`.
- `agent.py` passe de 901 à 867 lignes.

### Validation isolée réalisée avant versionnage

- Compilation des nouveaux modules, du Runner et des tests : réussie.
- Escalade : politique, bornes, succès et erreur Council : réussis.
- Apprentissage : résident, dédié, repli de configuration et suivi anti-GC : réussis.
- Régressions finalisation, Council, Cortex et Ultra cloud-only : réussies.
- Architecture : 344 outils, 346 routes, 40 pages et 64 outils encadrés.

### Rollback

- Revenir au commit v2.306 et replacer les deux effets dans `agent.py`.
  Aucun contrat SSE, modèle Council, réglage d'apprentissage ou outil n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 88/88 étapes réussies en 124,1 secondes.
- Backend compilé : 159 fichiers Python.
- Frontend : 0 erreur ESLint ; 37 avertissements historiques, hors périmètre de cette tranche.
- Redémarrage réel : `/api/health` expose `2.307.0`, Ollama disponible, 344/344 outils et
  15 workers supervisés.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.

## 2026-07-27 — v2.306.0 — Issue idempotente des compétences

### Constat et décision

- `agent.py` contenait encore une closure mutable pour enregistrer l'issue d'une compétence,
  mémoriser un parcours gagnant et programmer une auto-amélioration après échec d'outil.
- Cette responsabilité est appelée depuis les deux sorties du Runner et doit rester
  strictement idempotente afin de ne pas doubler les statistiques ni les tâches LLM.

### Implémentation

- Nouveau `backend/agent_skill_outcome.py` avec `SkillOutcomeRecorder`.
- Le succès conserve le golden path historique.
- L'échec programme une seule amélioration via le registre de tâches anti-GC.
- Les imports `skills` et `tools` restent tardifs pour éviter d'alourdir le chargement du Runner.
- Nouveau `scripts/test_agent_skill_outcome.py`, intégré à `check_marvin --quick`.
- `agent.py` passe de 933 à 901 lignes.

### Validation isolée réalisée avant versionnage

- Compilation du nouveau module, du Runner et du test : réussie.
- Succès, échec, idempotence et auto-amélioration : réussis.
- Régressions finalisation générale et état du Runner : réussies.
- Architecture : 344 outils, 346 routes, 40 pages et 64 outils encadrés.

### Rollback

- Revenir au commit v2.305 et replacer la finalisation de compétence dans `agent.py`.
  Aucun contrat SSE, format de statistique, compétence ou outil n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 86/86 étapes réussies en 116,5 secondes.
- Backend compilé : 157 fichiers Python.
- Frontend : 0 erreur ESLint ; 37 avertissements historiques, hors périmètre de cette tranche.
- Redémarrage réel : `/api/health` expose `2.306.0`, Ollama disponible, 344/344 outils et
  15 workers supervisés.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.

## 2026-07-27 — v2.305.0 — Post-validation des résultats d'outils

### Constat et décision

- Après le dispatch et l'exécution, la boucle du Runner normalisait encore le contrat commun,
  lançait une critique des actions dangereuses en attente de confirmation et inspectait le
  texte des documents générés.
- Ces contrôles portent sur un résultat déjà obtenu. Ils doivent rester isolés : leur propre
  panne ne doit jamais annoncer à tort que l'action métier a échoué.

### Implémentation

- Nouveau `backend/agent_tool_postprocess.py`.
- La normalisation `_contract` conserve les champs historiques du résultat.
- La critique est limitée aux outils dangereux retournant `requiresConfirmation`.
- Les quatre outils documentaires historiques restent inspectés avec le scanner déterministe.
- Les trois observateurs sont best-effort et testables par injection.
- Nouveau `scripts/test_agent_tool_postprocess.py`, intégré à `check_marvin --quick`.
- `agent.py` passe de 962 à 933 lignes.

### Validation isolée réalisée avant versionnage

- Compilation du module, du Runner et du test : réussie.
- Contrat, critique, scan documentaire et isolation d'exception : réussis.
- Régressions observabilité, revue et sécurité : réussies.
- Architecture : 344 outils, 346 routes, 40 pages et 64 outils encadrés.

### Rollback

- Revenir au commit v2.304 et replacer ces trois contrôles dans `agent.py`.
  Aucun résultat complet, reçu, événement SSE, outil ou route n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 85/85 étapes réussies en 108,5 secondes.
- Backend compilé : 156 fichiers Python.
- Frontend : 0 erreur ESLint ; 37 avertissements historiques, hors périmètre de cette tranche.
- Redémarrage réel : `/api/health` expose `2.305.0`, Ollama disponible, 344/344 outils et
  15 workers supervisés.
- `scripts/smoke_test_api.py` : 28/28 contrats HTTP réussis.

## 2026-07-27 — v2.304.0 — Politique de dispatch des outils

### Constat et décision

- La boucle du Runner décidait encore elle-même si un outil devait être exécuté ou bloqué :
  polling répété, substitution d'un outil explicitement demandé, commande demandée en texte,
  arguments invalides, permission Sécurisée et confirmation Expert.
- Cette décision précède l'exécuteur idempotent et constitue une politique déterministe
  indépendante du transport Ollama et du SSE.
- Les tests ont révélé une incohérence existante : le niveau Sécurisé, défini comme lecture
  seule, bloquait `pc_run_command` et `pc_run_elevated` mais pas `pc_run_powershell`.

### Implémentation

- Nouveau `backend/agent_tool_dispatch.py` avec requête et résultat typés.
- Les six branches de blocage/autorisation sont centralisées et injectent le validateur ainsi
  que l'exécuteur existants.
- Les opérations irréversibles ou sortantes restent non confirmées même en Expert afin que
  leur outil exige toujours l'accord humain.
- `pc_run_powershell` rejoint `SECURE_BLOCKED_TOOLS`; Standard et Expert sont inchangés.
- Nouveau `scripts/test_agent_tool_dispatch.py`, intégré à `check_marvin --quick`.
- `agent.py` passe de 1 069 à 960 lignes.

### Validation isolée réalisée avant versionnage

- Compilation du module, du Runner et du test : réussie.
- Polling, outil explicite, texte, validation, Sécurisé et Expert : réussis.
- Régressions politiques, sécurité et garde-fous d'intention : réussies.
- Architecture : 344 outils, 346 routes, 40 pages et 64 outils encadrés.

### Rollback

- Revenir au commit v2.303, replacer la politique dans `agent.py` et retirer
  `pc_run_powershell` de `SECURE_BLOCKED_TOOLS`. Aucun outil ni route n'est supprimé.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 84/84 étapes réussies après correction des deux
  régressions de frontière détectées; compilation de 155 fichiers Python, cohérence 344/344
  outils et ESLint sans erreur.
- Backend réel redémarré : processus lancé PID 32392, version `2.304.0`, Ollama disponible,
  344 outils et 15 workers observés.
- `scripts/smoke_test_api.py` : 28/28 contrats réussis avec le frontend Turbopack actif.

## 2026-07-26 — v2.303.0 — Préparation déterministe d'une étape d'outil

### Constat et décision

- La boucle du Runner normalisait directement deux variantes réellement émises par les LLM,
  injectait les identifiants de conversation et compactait les résultats volumineux.
- Ces transformations sont déterministes et doivent être testables sans lancer un modèle.
  L'exécution, les permissions, les reçus, la critique et l'observabilité restent dans leurs
  frontières existantes.

### Implémentation

- Nouveau `backend/agent_tool_step.py` avec `PreparedToolCall`.
- `command` est normalisé vers `script` pour PowerShell et l'ancien `ssh_connect(save=true)`
  vers `ssh_connection_save`, comme avant.
- Les identifiants `_conversation_id` sont injectés dans une copie des arguments après
  l'événement public `tool_start`; le LLM n'a pas à les connaître ni à les inventer.
- La projection Ollama conserve les champs critiques, borne textes et listes volumineux,
  tandis que le résultat intégral reste envoyé au frontend et persisté.
- Nouveau `scripts/test_agent_tool_step.py`, intégré à `check_marvin --quick`.

### Validation isolée réalisée avant versionnage

- Compilation du module, du Runner et du test : réussie.
- Alias, JSON invalide, signature, contexte interne et projection bornée : réussis.
- Régressions exécution, observabilité et Code Workspace : réussies.
- Architecture : 344 outils, 346 routes et 40 pages.

### Rollback

- Revenir au commit v2.302 et replacer ces transformations dans `agent.py`.
  Aucun reçu, événement SSE, outil, route, schéma ou résultat complet n'est modifié.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 83/83 étapes réussies; compilation de 154 fichiers
  Python, cohérence 344/344 outils et ESLint sans erreur.
- Backend réel redémarré : processus lancé PID 33600, version `2.303.0`, Ollama disponible,
  344 outils et 15 workers observés.
- `scripts/smoke_test_api.py` : 28/28 contrats réussis avec le frontend Turbopack actif.

## 2026-07-26 — v2.302.0 — Matérialisation déterministe des outils obligatoires

### Constat et décision

- La boucle du Runner construisait directement les arguments de Council, Cortex, Research
  Swarm, Code Forge, Code Workspace, recherche, mission longue et génération documentaire.
- Cette logique est un contrat déterministe entre le plan de tour et l'exécution, pas une
  responsabilité du transport Ollama. Elle est extraite sans forcer prématurément le modèle :
  tant qu'il agit et que le budget reste suffisant, Marvin conserve son autonomie.

### Implémentation

- Nouveau `backend/agent_required_tools.py` avec contextes et résultat typés.
- Un outil déjà exécuté ou déjà émis dans l'étape n'est jamais dupliqué.
- L'injection intervient si le modèle tente de conclure sans satisfaire le contrat, ou dans
  les deux dernières étapes du budget.
- La reprise d'un script/code/projet dans Code Workspace reçoit au maximum les 16 000 derniers
  caractères du livrable assistant précédent, comme auparavant.
- Nouveau `scripts/test_agent_required_tools.py`, intégré à `check_marvin --quick`.

### Validation isolée réalisée avant versionnage

- Compilation du module, du Runner et du test : réussie.
- Contrats, ordre, dédoublonnage, autonomie avant fin de budget et contexte Workspace : réussis.
- Régressions planification, Council et service Code Workspace : réussies.
- Architecture : 344 outils, 346 routes et 40 pages.

### Rollback

- Revenir au commit v2.301 et replacer la construction des arguments dans `agent.py`.
  Aucun format d'appel, identifiant, outil, route, modèle ou donnée persistée n'est migré.

### Validation complète et réelle après versionnage

- `scripts/check_marvin.py --quick` : 82/82 étapes réussies; compilation de 153 fichiers
  Python, cohérence 344/344 outils et ESLint sans erreur.
- Backend réel redémarré : processus lancé PID 29172, version `2.302.0`, Ollama disponible,
  344 outils et 15 workers observés.
- `scripts/smoke_test_api.py` : 28/28 contrats réussis avec le frontend Turbopack actif.
## 2026-07-27 — v2.313.0 — Clôture de la phase Runner

### Demande

- Poursuivre la consolidation sans perte de fonctionnalité.
- Profiter de chaque tranche pour corriger et retravailler les défauts établis.
- Tester chaque modification avant de passer à la suite.

### Constats et décisions

- L'escalade d'une compétence du profil chat vers agent utilisait
  `AUTO_MODE_FALLBACKS` sans l'importer : ce chemin rare pouvait lever `NameError`.
- Sept variables/imports résiduels n'avaient plus aucun lecteur après les extractions
  précédentes; ils ont été retirés après recherche globale.
- Les dernières politiques métier encore mêlées à la boucle étaient le repli local sensible,
  la relance unique d'une compétence, le refus Forge et la synthèse après épuisement du budget.
- Ces politiques sont maintenant injectables et testables dans `agent_loop_policy.py` et
  `agent_budget_completion.py`; `run_agent` reste le composition root du Runner.
- La synthèse de repli ne demande plus de reformuler la requête après un long travail : elle
  expose l'incomplétude et propose de continuer, sans annoncer de succès non vérifié.

### Fichiers

- `backend/agent.py`
- `backend/agent_loop_policy.py`
- `backend/agent_budget_completion.py`
- `scripts/test_agent_loop_policy.py`
- `scripts/check_marvin.py`
- `backend/app_version.py`, `backend/main.py`
- `README.md`, `AGENTS.md`, `ARCHITECTURE.md`
- `BACKEND-CONSOLIDATION-PLAN.md`, `package.json`, `package-lock.json`

### Validation réelle

- Test ciblé `test_agent_loop_policy.py` : réussi, y compris import runtime de
  `AUTO_MODE_FALLBACKS`, repli sensible, exception Ultra, relance Skill, refus Forge,
  synthèse nominale et repli sur panne de transport.
- `scripts/check_marvin.py --quick` : **95/95 étapes réussies**.
- Compilation de l'ensemble du backend : réussie.
- Architecture : **344/344 outils**, **346 routes**, **40 pages** et
  **64 outils encadrés**.
- Frontend : **0 erreur**, 37 avertissements historiques.
- Redémarrage réel : `/api/health` expose **2.313.0**, Ollama disponible,
  **344/344 outils** et **15 workers**.
- Smoke test réel avec frontend Turbopack : **28/28 contrats HTTP réussis**.
- `agent.py` passe de 560 à **533 lignes**.
- `git diff --check` : réussi; seuls les avertissements de conversion LF/CRLF Windows
  attendus sont présents.
## 2026-07-27 — v2.314.0 — Domaine de mutation des fichiers

### Demande

- Poursuivre la phase B après clôture du Runner.
- Améliorer le code pendant l'extraction sans retirer de fonctionnalité.

### Constats et décisions

- Six opérations cohésives de mutation étaient encore implémentées directement dans
  `tools.py`.
- La résolution des chemins Windows reste la responsabilité portable de la façade et est
  injectée explicitement dans le domaine.
- Les fonctions du registre restent les mêmes objets que les fonctions du domaine; aucun
  wrapper divergent n'est ajouté.
- La déduplication d'une destination était une boucle sans borne. Elle est maintenant bornée
  à 10 000 collisions et produit une erreur explicite dans ce cas extrême.
- Une recherche globale confirme que `_dedupe_path` et `_normalize_dest` n'avaient aucun
  consommateur externe.

### Fichiers

- `backend/tool_domains/filesystem.py`
- `backend/tools.py`
- `scripts/test_tool_domain_filesystem.py`
- `scripts/check_marvin.py`
- `backend/app_version.py`, `backend/main.py`
- `README.md`, `AGENTS.md`, `ARCHITECTURE.md`
- `BACKEND-CONSOLIDATION-PLAN.md`, `package.json`, `package-lock.json`

### Validation réelle

- Test ciblé `test_tool_domain_filesystem.py` : réussi pour création, écriture,
  ajout, collision de copie, renommage, déplacement identique, confirmation et suppression.
- Compatibilité de façade : les six objets fonctions du registre sont ceux du domaine.
- `scripts/check_marvin.py --quick` : **96/96 étapes réussies**.
- Architecture : **344/344 outils**, **346 routes**, **40 pages** et
  **64 outils encadrés**.
- Compilation complète du backend et cohérence des dépendances : réussies.
- Frontend : **0 erreur**, 37 avertissements historiques.
- Redémarrage réel : `/api/health` expose **2.314.0**, Ollama disponible,
  **344/344 outils** et **15 workers**.
- Smoke test avec frontend Turbopack : **28/28 contrats HTTP réussis**.
- `tools.py` passe de 20 197 à **20 070 lignes**.
- `git diff --check` : réussi; seuls les avertissements LF/CRLF Windows attendus subsistent.

## 2026-07-27 — v2.315.0 — Inventaire et intégrité des fichiers

### Demande

- Continuer la phase B par responsabilités cohésives et améliorer les défauts établis.

### Constats et décisions

- `file_list` et `file_info` partageaient résolution de chemin, formatage des tailles et
  métadonnées avec le nouveau domaine filesystem.
- L'option `hash=true` ne fournissait que MD5. Le champ reste présent pour compatibilité,
  mais SHA-256 est calculé dans la même lecture par blocs et ajouté au contrat de résultat.
- Les erreurs de chemin, permissions, fichiers cachés et comptages de dossiers conservent
  leur comportement public.

### Fichiers

- `backend/tool_domains/filesystem.py`
- `backend/tools.py`
- `scripts/test_tool_domain_filesystem.py`
- `backend/app_version.py`, `backend/main.py`
- `README.md`, `AGENTS.md`, `BACKEND-CONSOLIDATION-PLAN.md`
- `package.json`, `package-lock.json`

### Validation réelle

- Test filesystem ciblé : inventaire, catégorie Texte, taille exacte, MD5, SHA-256 et
  identités de façade réussis, en plus des mutations déjà couvertes.
- `scripts/check_marvin.py --quick` : **96/96 étapes réussies**.
- Architecture : **344/344 outils**, **346 routes**, **40 pages** et
  **64 outils encadrés**.
- Compilation complète et dépendances Python : réussies.
- Frontend : **0 erreur**, 37 avertissements historiques.
- Redémarrage réel : `/api/health` expose **2.315.0**, Ollama disponible,
  **344/344 outils** et **15 workers**.
- Smoke test avec frontend Turbopack : **28/28 contrats HTTP réussis**.
- `tools.py` passe de 20 070 à **19 950 lignes**.
- `git diff --check` : réussi; seuls les avertissements LF/CRLF Windows attendus subsistent.
## 2026-07-27 — v2.316.0 — Lecture multi-format des fichiers

### Demande

- Continuer l'extraction des outils fichiers en corrigeant les défauts établis.

### Constats et décisions

- Le lecteur historique annonçait `.doc` et `.xls`, alors que `python-docx` et `openpyxl`
  ne prennent pas en charge ces formats binaires.
- Le classeur XLSX n'était pas fermé si une exception survenait pendant l'itération et ses
  noms de feuilles étaient consultés après `close()`.
- La lecture de snapshot Code Workspace refusé reste strictement bornée au chemin
  `data/coding_workspaces/<mission>/repo`.
- Les formats réellement supportés restent PDF, DOCX, XLSX, CSV et texte multi-encodage.
  Les formats anciens produisent désormais une erreur explicite avec instruction de conversion.
- Tous les lecteurs exposent `content_truncated` sans retirer les anciens champs.

### Fichiers

- `backend/tool_domains/filesystem.py`
- `backend/tools.py`
- `scripts/test_tool_domain_filesystem.py`
- `backend/app_version.py`, `backend/main.py`
- `README.md`, `AGENTS.md`, `BACKEND-CONSOLIDATION-PLAN.md`
- `package.json`, `package-lock.json`

### Validation réelle

- Test filesystem ciblé : texte, CSV, troncature et erreur `.xls` explicite réussis;
  l'identité `tools.execute_file_read is filesystem.read` est vérifiée.
- `scripts/check_marvin.py --quick` : **96/96 étapes réussies**.
- Architecture : **344/344 outils**, **346 routes**, **40 pages** et
  **64 outils encadrés**.
- Compilation complète et dépendances Python : réussies.
- Frontend : **0 erreur**, 37 avertissements historiques.
- Redémarrage réel : `/api/health` expose **2.316.0**, Ollama disponible,
  **344/344 outils** et **15 workers**.
- Smoke test avec frontend Turbopack : **28/28 contrats HTTP réussis**.
- `tools.py` passe de 19 950 à **19 838 lignes**.
- `git diff --check` : réussi; seuls les avertissements LF/CRLF Windows attendus subsistent.
## 2026-07-27 — v2.317.0 — Recherche de fichiers bornée

### Demande

- Continuer la consolidation des outils et corriger les fragilités rencontrées.

### Constats et décisions

- `file_find` et ses deux moteurs partageaient une responsabilité unique mais vivaient au
  milieu de `tools.py`.
- `max_results` acceptait une conversion directe et aucune borne avant son interpolation
  dans `SELECT TOP`.
- Les objets ADO pouvaient ne pas être fermés lorsque la lecture d'un champ ou le parcours
  du recordset échouait.
- Le domaine valide désormais l'entier entre 1 et 1000, ferme recordset, connexion et COM
  en `finally`, et maintient Windows Search comme chemin rapide avec `os.walk` en repli.
- Les deux moteurs bloquants sont exécutés avec `asyncio.to_thread`.

### Fichiers

- `backend/tool_domains/filesystem.py`
- `backend/tools.py`
- `scripts/test_tool_domain_filesystem.py`
- `backend/app_version.py`, `backend/main.py`
- `README.md`, `AGENTS.md`, `BACKEND-CONSOLIDATION-PLAN.md`
- `package.json`, `package-lock.json`

### Validation réelle

- Test filesystem ciblé : fallback `os.walk`, glob, limite invalide et identité de façade
  réussis, en complément de toute la couverture fichiers précédente.
- `scripts/check_marvin.py --quick` : **96/96 étapes réussies**.
- Architecture : **344/344 outils**, **346 routes**, **40 pages** et
  **64 outils encadrés**.
- Compilation complète et dépendances Python : réussies.
- Frontend : **0 erreur**, 37 avertissements historiques.
- Redémarrage réel : `/api/health` expose **2.317.0**, Ollama disponible,
  **344/344 outils** et **15 workers**.
- Smoke test avec frontend Turbopack : **28/28 contrats HTTP réussis**.
- `tools.py` passe de 19 838 à **19 654 lignes**.
- `git diff --check` : réussi; seuls les avertissements LF/CRLF Windows attendus subsistent.
## 2026-07-27 — v2.318.0 — Recherche de contenu observable

### Demande

- Continuer l'extraction des outils fichiers et améliorer les défauts rencontrés.

### Constats et décisions

- Une extension fournie sous forme de chaîne était traitée comme une collection de caractères.
- `max_results` n'était ni converti ni borné; une valeur textuelle interrompait l'outil.
- Un dossier inexistant retournait un faux succès sans résultat.
- L'énumération chargeait tous les candidats en mémoire sans limite.
- La nouvelle frontière normalise les extensions, borne les résultats à 1000 et les candidats
  à 50 000, ignore les répertoires de dépendances usuels et expose les compteurs utiles.
- La valeur par défaut de `max_files` est 5000; `candidate_limit_reached` signale explicitement
  qu'une recherche plus ciblée est nécessaire.

### Fichiers

- `backend/tool_domains/filesystem.py`
- `backend/tools.py`
- `scripts/test_tool_domain_filesystem.py`
- `backend/app_version.py`, `backend/main.py`
- `README.md`, `AGENTS.md`, `BACKEND-CONSOLIDATION-PLAN.md`
- `package.json`, `package-lock.json`

### Validation réelle

- Test filesystem ciblé : extension chaîne CSV, résultat trouvé, borne non atteinte,
  dossier absent et identité de façade réussis.
- `scripts/check_marvin.py --quick` : **96/96 étapes réussies**.
- Architecture : **344/344 outils**, **346 routes**, **40 pages** et
  **64 outils encadrés**.
- Compilation complète et dépendances Python : réussies.
- Frontend : **0 erreur**, 37 avertissements historiques.
- Redémarrage réel : `/api/health` expose **2.318.0**, Ollama disponible,
  **344/344 outils** et **15 workers**.
- Smoke test avec frontend Turbopack : **28/28 contrats HTTP réussis**.
- `tools.py` passe de 19 654 à **19 592 lignes**.
- `git diff --check` : réussi; seuls les avertissements LF/CRLF Windows attendus subsistent.
## 2026-07-27 — v2.319.0 — Formatage documentaire partagé

### Demande

- Préparer l'extraction DOCX/PDF sans dupliquer leur logique de rendu.

### Constats et décisions

- Les générateurs DOCX et PDF dépendent de la même grammaire Markdown, mais celle-ci vivait
  comme helpers privés au milieu de `tools.py`.
- Les helpers sont extraits vers `document_formatting.py` et réexposés sous leurs alias
  historiques pour les consommateurs internes et l'API existante.
- Titres, paragraphes, listes, citations, séparateurs, code, tableaux et images sont couverts.
- Une URL Markdown contenant un guillemet pouvait produire un attribut XML ReportLab invalide;
  les guillemets sont maintenant encodés en `&quot;`.

### Fichiers

- `backend/document_formatting.py`
- `backend/tools.py`
- `scripts/test_document_formatting.py`
- `scripts/check_marvin.py`
- `backend/app_version.py`, `backend/main.py`
- `README.md`, `AGENTS.md`, `ARCHITECTURE.md`
- `BACKEND-CONSOLIDATION-PLAN.md`, `package.json`, `package-lock.json`

### Validation réelle

- Test `test_document_formatting.py` : blocs, tableau, code, image, gras, italique,
  code inline, lien, échappement HTML, URL avec guillemets et alias réussis.
- `scripts/check_marvin.py --quick` : **97/97 étapes réussies**.
- Architecture : **344/344 outils**, **346 routes**, **40 pages** et
  **64 outils encadrés**.
- Compilation complète et dépendances Python : réussies.
- Frontend : **0 erreur**, 37 avertissements historiques.
- Redémarrage réel : `/api/health` expose **2.319.0**, Ollama disponible,
  **344/344 outils** et **15 workers**.
- Smoke test avec frontend Turbopack : **28/28 contrats HTTP réussis**.
- `tools.py` passe de 19 592 à **19 511 lignes**.
- `git diff --check` : réussi; seuls les avertissements LF/CRLF Windows attendus subsistent.
## 2026-07-27 — v2.320.0 — Profil documentaire

### Demande

- Découpler préférences et modèles avant l'extraction des générateurs DOCX/PDF.

### Constats et décisions

- L'identité persistante et le catalogue de dix modèles étaient mélangés aux traitements de
  génération dans `tools.py`.
- `get_identity` retourne désormais une copie de la valeur SQLite pour éviter une mutation
  indirecte de l'objet fourni par la persistance.
- La mise à jour n'accepte que neuf champs documentaires connus, normalise les chaînes et
  préserve les valeurs existantes ainsi que la possibilité de vider explicitement un champ.
- La liste publique retourne une copie des sections; un consommateur ne peut plus modifier
  accidentellement le catalogue global.
- Les quatre alias historiques restent identiques pour `api/documents.py` et `tools.py`.

### Fichiers

- `backend/document_profile.py`
- `backend/tools.py`
- `scripts/test_document_profile.py`
- `scripts/check_marvin.py`
- `backend/app_version.py`, `backend/main.py`
- `README.md`, `AGENTS.md`, `ARCHITECTURE.md`
- `BACKEND-CONSOLIDATION-PLAN.md`, `package.json`, `package-lock.json`

### Validation réelle

- Test `test_document_profile.py` : liste blanche, normalisation, conservation, vidage,
  absence de mutation source, dix modèles, copies défensives et quatre alias réussis.
- `scripts/check_marvin.py --quick` : **98/98 étapes réussies**.
- Architecture : **344/344 outils**, **346 routes**, **40 pages** et
  **64 outils encadrés**.
- Compilation complète et dépendances Python : réussies.
- Frontend : **0 erreur**, 37 avertissements historiques.
- Redémarrage réel : `/api/health` expose **2.320.0**, Ollama disponible,
  **344/344 outils** et **15 workers**.
- Smoke test avec frontend Turbopack : **28/28 contrats HTTP réussis**.
- `tools.py` passe de 19 511 à **19 468 lignes**.
- `git diff --check` : réussi; seuls les avertissements LF/CRLF Windows attendus subsistent.
## 2026-07-27 — v2.321.0 — Domaine DOCX et conversions

### Demande

- Extraire les générateurs documentaires derrière une frontière testable sans perte de rendu.

### Constats et décisions

- Création DOCX, DOCX→PDF et PDF→DOCX forment une frontière cohérente autour des bibliothèques
  documentaires et du résolveur de chemins.
- Le domaine reçoit le résolveur portable par injection; formatage et identité proviennent
  des modules partagés extraits aux versions précédentes.
- `convert_docx_to_pdf` acceptait tout fichier avant de lancer Word et ne créait pas
  explicitement le dossier de sortie. La source doit maintenant être un fichier `.docx` et
  la destination est préparée avant le thread COM.
- Le modèle COM dédié à usage unique et le `finally` de `pdf2docx` sont conservés.
- Un vrai fichier DOCX est généré puis relu; titre, texte enrichi et cellule de tableau sont
  vérifiés, au lieu de se limiter à un mock.

### Fichiers

- `backend/tool_domains/documents.py`
- `backend/tools.py`
- `scripts/test_tool_domain_documents.py`
- `scripts/check_marvin.py`
- `backend/app_version.py`, `backend/main.py`
- `README.md`, `AGENTS.md`, `ARCHITECTURE.md`
- `BACKEND-CONSOLIDATION-PLAN.md`, `package.json`, `package-lock.json`

### Validation réelle

- Test `test_tool_domain_documents.py` : génération DOCX réelle, réouverture, titre,
  texte enrichi, tableau, source invalide, conversion non supportée et trois alias réussis.
- `scripts/check_marvin.py --quick` : **99/99 étapes réussies**.
- Architecture : **344/344 outils**, **346 routes**, **40 pages** et
  **64 outils encadrés**.
- Compilation complète et dépendances Python : réussies.
- Frontend : **0 erreur**, 37 avertissements historiques.
- Redémarrage réel : `/api/health` expose **2.321.0**, Ollama disponible,
  **344/344 outils** et **15 workers**.
- Smoke test avec frontend Turbopack : **28/28 contrats HTTP réussis**.
- `tools.py` passe de 19 468 à **19 165 lignes**.
- `git diff --check` : réussi; seuls les avertissements LF/CRLF Windows attendus subsistent.
## 2026-07-27 — v2.322.0 — Génération IA documentaire

### Demande

- Achever la frontière DOCX en déplaçant l'orchestration IA sans modifier son routage modèle.

### Constats et décisions

- `document_generate` dépendait de la position de `tools.py` via `__file__`; son déplacement
  naïf aurait écrit dans un autre dossier.
- Le générateur LLM et `data/documents_generes` sont maintenant injectés explicitement après
  la définition du transport historique `_ollama_generate`.
- Modes rapide/détaillé, rappel d'auteur, RAG documentaire, en-tête, références, signature,
  sidecar Markdown et conversion PDF optionnelle sont conservés.
- Le test injecte un LLM déterministe, génère le DOCX final dans un dossier contrôlé et
  vérifie que le fichier existe.
- Une première compilation a détecté que l'alias `execute_file_search_text`, situé entre les
  blocs historiques, avait été retiré avec l'ancien générateur. Il a été restauré avant toute
  version et les tests Filesystem + Documents ainsi que l'architecture ont été rejoués.

### Fichiers

- `backend/tool_domains/documents.py`
- `backend/tools.py`
- `scripts/test_tool_domain_documents.py`
- `backend/app_version.py`, `backend/main.py`
- `README.md`, `AGENTS.md`, `BACKEND-CONSOLIDATION-PLAN.md`
- `package.json`, `package-lock.json`

### Validation réelle

- Tests ciblés Documents et Filesystem : génération IA injectée, chemin de sortie,
  fichier final, quatre alias documentaires et alias de recherche restauré réussis.
- `scripts/check_marvin.py --quick` : **99/99 étapes réussies**.
- Architecture : **344/344 outils**, **346 routes**, **40 pages** et
  **64 outils encadrés**.
- Compilation complète et dépendances Python : réussies.
- Frontend : **0 erreur**, 37 avertissements historiques.
- Redémarrage réel : `/api/health` expose **2.322.0**, Ollama disponible,
  **344/344 outils** et **15 workers**.
- Smoke test avec frontend Turbopack : **28/28 contrats HTTP réussis**.
- `tools.py` passe de 19 165 à **19 044 lignes**.
- `git diff --check` : réussi; seuls les avertissements LF/CRLF Windows attendus subsistent.
## 2026-07-27 — v2.323.0 — Générateur PDF natif

### Demande

- Fermer la frontière documentaire principale en extrayant le rendu PDF natif.

### Constats et décisions

- `file_create_pdf` partageait déjà formatage, identité et résolveur avec le domaine
  Documents mais restait un bloc de 331 lignes dans `tools.py`.
- La fonction rejoint le domaine sans modifier ses styles, son TOC multi-passe, sa
  pagination, les tableaux, images, blocs de code, ASCII art et nettoyages temporaires.
- Les consommateurs historiques continuent d'appeler le même objet via la façade.
- Le test produit un PDF réel, vérifie l'en-tête binaire `%PDF`, extrait son texte avec
  `pypdf` et contrôle titre et contenu.

### Fichiers

- `backend/tool_domains/documents.py`
- `backend/tools.py`
- `scripts/test_tool_domain_documents.py`
- `backend/app_version.py`, `backend/main.py`
- `README.md`, `AGENTS.md`, `BACKEND-CONSOLIDATION-PLAN.md`
- `package.json`, `package-lock.json`

### Validation réelle

- Test Documents : PDF réel, signature `%PDF`, relecture `pypdf`, titre, contenu et
  cinquième alias de façade réussis, en plus des contrôles DOCX/conversions/génération IA.
- `scripts/check_marvin.py --quick` : **99/99 étapes réussies**.
- Architecture : **344/344 outils**, **346 routes**, **40 pages** et
  **64 outils encadrés**.
- Compilation complète et dépendances Python : réussies.
- Frontend : **0 erreur**, 37 avertissements historiques.
- Redémarrage réel : `/api/health` expose **2.323.0**, Ollama disponible,
  **344/344 outils** et **15 workers**.
- Smoke test avec frontend Turbopack : **28/28 contrats HTTP réussis**.
- `tools.py` passe de 19 044 à **18 716 lignes**.
- `git diff --check` : réussi; seuls les avertissements LF/CRLF Windows attendus subsistent.

## 2026-07-27 — v2.324.0 — Domaine Archives borné

### Demande

- Poursuivre la consolidation backend et améliorer les implémentations fragiles rencontrées,
  sans retirer de fonctionnalité.

### Constats et décisions

- `file_compress` et `file_extract` restaient implémentés dans `tools.py`.
- L'extraction utilisait directement `ZipFile.extractall()` et `TarFile.extractall()` :
  aucun confinement des chemins internes n'empêchait une archive hostile d'écrire hors de la
  destination, et liens ou fichiers spéciaux TAR n'étaient pas filtrés.
- Les deux outils rejoignent `tool_domains/archives.py` avec le résolveur portable injecté.
- La création ZIP passe par un fichier temporaire puis `os.replace`; le fichier de sortie est
  exclu si la destination se trouve dans un dossier source.
- L'extraction traite chaque membre après validation du chemin, du type, du nombre d'entrées,
  de la taille décompressée et du taux de compression. Les liens ZIP/TAR et fichiers spéciaux
  TAR sont refusés. ZIP, TAR, TAR.GZ, TAR.BZ2, TAR.XZ et TGZ restent pris en charge.
- Les objets historiques `execute_file_compress` et `execute_file_extract` restent les
  identités enregistrées par la façade; aucune spécification ni fonctionnalité publique
  n'est supprimée.

### Fichiers

- `backend/tool_domains/archives.py`
- `backend/tools.py`
- `scripts/test_tool_domain_archives.py`
- `scripts/check_marvin.py`
- `backend/app_version.py`, `backend/main.py`
- `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, `BACKEND-CONSOLIDATION-PLAN.md`
- `package.json`, `package-lock.json`

### Validation réelle

- Test Archives : ZIP réel créé puis relu, TAR.GZ réel extrait, traversée ZIP et lien TAR
  hostiles refusés, format inconnu refusé et identités de façade contrôlées.
- `scripts/check_marvin.py --quick` : **100/100 étapes réussies**.
- Architecture : **344/344 outils**, **346 routes**, **40 pages** et
  **64 outils encadrés**.
- Compilation complète et dépendances Python : réussies.
- Frontend : **0 erreur**, 37 avertissements historiques.
- Redémarrage réel : `/api/health` expose **2.324.0**, Ollama disponible,
  **344/344 outils** et **15 workers**.
- Smoke test avec frontend Turbopack : **28/28 contrats HTTP réussis**.
- `tools.py` passe de 18 716 à **18 632 lignes**.
- `git diff --check` : réussi; seuls les avertissements LF/CRLF Windows attendus subsistent.

## 2026-07-27 — v2.325.0 — Domaine Tableurs

### Demande

- Continuer la consolidation backend, améliorer les défauts rencontrés et vérifier chaque
  évolution sur des artefacts réellement exploitables.

### Constats et décisions

- Les quatre outils de création/lecture XLSX et de conversion CSV étaient dispersés dans
  `tools.py`.
- La fusion du titre utilisait `chr(64 + nombre_colonnes)` et devenait invalide dès la
  colonne 27. Les noms de feuille et délimiteurs n'étaient pas validés, le CSV était chargé
  intégralement en mémoire et certains classeurs pouvaient rester ouverts après exception.
- Les quatre outils rejoignent `tool_domains/spreadsheets.py` avec le résolveur portable
  injecté et les mêmes identités publiques.
- Les coordonnées de fusion utilisent désormais openpyxl, les écritures XLSX/CSV sont
  atomiques, le CSV est traité en flux avec un plafond explicite, les lectures sont bornées
  et chaque classeur est fermé dans un `finally`.
- Les formats XLSX et CSV, les styles, formules, modes `read/sheets/summary`, choix de feuille
  et détection de délimiteur restent disponibles.

### Fichiers

- `backend/tool_domains/spreadsheets.py`
- `backend/tools.py`
- `scripts/test_tool_domain_spreadsheets.py`
- `scripts/check_marvin.py`
- `backend/app_version.py`, `backend/main.py`
- `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, `BACKEND-CONSOLIDATION-PLAN.md`
- `package.json`, `package-lock.json`

### Validation réelle

- Test Tableurs : XLSX réel de 28 colonnes créé et rouvert, fusion `A1:AB1`, formule,
  dimensions, résumé, liste des feuilles, lecture bornée et cycle CSV→XLSX→CSV vérifiés.
- `scripts/check_marvin.py --quick` : **101/101 étapes réussies**.
- Architecture : **344/344 outils**, **346 routes**, **40 pages** et
  **64 outils encadrés**.
- Compilation complète et dépendances Python : réussies.
- Frontend : **0 erreur**, 37 avertissements historiques.
- Redémarrage réel : `/api/health` expose **2.325.0**, Ollama disponible,
  **344/344 outils** et **15 workers**.
- Smoke test avec frontend Turbopack : **28/28 contrats HTTP réussis**.
- `tools.py` passe de 18 632 à **18 459 lignes**.
- `git diff --check` : réussi; seuls les avertissements LF/CRLF Windows attendus subsistent.
