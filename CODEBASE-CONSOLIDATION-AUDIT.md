# Audit de consolidation du code Marvin

Date : 2026-07-21  
Version observée avant correction : 2.255.0  
Périmètre : backend Python/FastAPI, frontend Next.js/React, avatar Electron, scripts Windows, tests, dépendances et organisation du dépôt.  
Décision de gouvernance : aucune extraction ou réorganisation de module ne doit être réalisée avant validation explicite de la stratégie avec Chaouki.

## 1. Résumé exécutif

Marvin possède déjà un socle de validation large : 36 contrôles rapides réussis, 107 fichiers Python compilés, 346 routes contrôlées, 344 outils cohérents avec leur schéma, 28 contrats API et 40 pages testées réellement. Le code fonctionne aujourd'hui et une réécriture globale ferait courir un risque injustifié.

La dette principale n'est pas limitée à `main.py`. Elle se concentre dans quelques noyaux fortement couplés, dans des erreurs trop souvent absorbées et dans une interface dont plusieurs pages cumulent rendu, état, accès réseau et logique métier. Le bon objectif n'est pas de « faire des fichiers plus petits » : il est de réduire les raisons de changer ensemble, rendre les dépendances explicites et conserver les contrats publics pendant chaque migration.

La stratégie recommandée est une migration incrémentale par façade et tests de caractérisation. Aucun big bang.

## 2. Faits établis

### Inventaire global

- 355 fichiers de projet inventoriés hors `node_modules`, environnements virtuels, caches, données et artefacts.
- 157 fichiers Python dans le dépôt, dont 107 sous `backend/`.
- 96 fichiers JavaScript/JSX/MJS sous `app/`, `components/` et `lib/`.
- 40 pages Next.js couvertes par le smoke test HTTP.
- 48 scripts de test ou smoke test.
- 37 routeurs FastAPI existent déjà sous `backend/api/`.
- `main.py` conserve 69 routes directes : chat/outils/MCP/cloud, e-mail et vidéo.

### Points de concentration

| Fichier | Lignes physiques | Signal principal |
|---|---:|---|
| `backend/tools.py` | 21 247 | 541 fonctions, registre de 344 outils, nombreuses responsabilités système et métier |
| `backend/main.py` | 5 545 | composition FastAPI, 69 routes, workers, cycle de vie, 62 dépendances backend directes |
| `backend/database.py` | 3 554 | schéma, migrations opportunistes et accès de nombreux domaines |
| `app/outils/page.jsx` | 3 406 | catalogue, formulaires, état et rendu dans une page |
| `backend/agent.py` | 3 188 | orchestration agentique, outils, modèles, compétences et persistance |
| `app/video/page.jsx` | 1 918 | plusieurs flux vidéo et composants dans une page |
| `components/chat/MessageBubble.jsx` | 1 586 | rendu de nombreux types de messages et résultats |
| `app/settings/page.jsx` | 1 383 | nombreux domaines de configuration |
| `app/emails/page.jsx` | 1 321 | comptes, boîte, automatisation, pièces jointes et règles |

La taille ne constitue pas à elle seule un défaut. Ici, elle est corrélée à un nombre élevé de responsabilités et de dépendances.

### Couplage et erreurs

- `main.py` dépend directement de 62 modules backend.
- `database` et `config` sont chacun importés par 33 modules ; ils sont les deux principaux centres de couplage.
- Analyse AST sur le backend : 889 captures de `Exception`/`BaseException`, 13 `except:` nus et 277 gestionnaires dont le corps se limite à `pass`.
- Certaines captures sont légitimes aux frontières best-effort ou pendant le nettoyage. Leur volume empêche néanmoins de distinguer facilement une dégradation attendue d'une panne perdue.
- Le gestionnaire HTTP global journalise les erreurs, mais renvoie actuellement `str(exc)` au client. Une politique d'erreur stable avec identifiant de corrélation serait plus maintenable et éviterait de coupler l'interface aux messages internes.

### Backend

Points solides :

- version publique centralisée ;
- `APIRouter` déjà employé sur 37 domaines ;
- invariants statiques sur routes et registres ;
- lifespan unique ;
- contrats explicites pour Code Forge, Test Forge et les environnements de validation ;
- chemins portables et capacités optionnelles contrôlés.

Points à consolider :

- `main.py` mélange composition, workers, orchestration proactive, modèles de requête et routes ;
- 16 tâches de fond sont créées et annulées manuellement dans un même lifespan ;
- plusieurs ressources et états transitent encore par des imports de modules/globals plutôt que par un état applicatif explicite ;
- `database.py` applique des `CREATE TABLE IF NOT EXISTS` et certains `ALTER TABLE` dans le code courant, sans registre de migrations versionnées visible ;
- `tools.py` est à la fois catalogue, implémentation, compatibilité et point de dispatch ;
- les modèles Pydantic restent parfois définis à proximité des routes au lieu de former des contrats de domaine réutilisables.

### Frontend

Points solides :

- Next.js 16.2.6 avec Turbopack conservé ;
- client backend centralisé dans `lib/backend.js` et vérifié par l'architecture ;
- une limite d'erreur globale existe ;
- 40/40 pages répondent réellement ;
- les parcours critiques chat, voix et avatar ont leurs tests déterministes.

Points à consolider :

- 67 composants clients, 333 appels `fetch` et 3 443 styles JSX inline ;
- plusieurs pages sont des « verticales complètes » trop volumineuses ;
- ESLint produit 37 avertissements, dont une part importante concerne les dépendances de hooks ;
- les dépendances manquantes des hooks peuvent produire des fermetures obsolètes, notamment dans les flux e-mail ;
- seul `app/error.js` a été trouvé comme frontière spéciale globale ; des `loading.js` et limites d'erreur par domaine peuvent isoler les pannes et améliorer la perception de latence ;
- la validation runtime Zod existe comme dépendance mais n'est pas encore un contrat uniforme pour les 333 appels réseau.

### Tests, qualité et livraison

Résultats réellement observés le 2026-07-21 :

- `npm run check:architecture` : succès, 344 outils, 346 routes, 40 pages ;
- `npm run check:quick` : 36/36 étapes ;
- compilation Python : 107 fichiers ;
- `npm run lint` : 0 erreur, 37 avertissements ;
- `npm run check:api` : 28/28 contrats ;
- `npm run check:pages` : 40/40 pages HTTP ;
- `npm run check:avatar` : 33/33 assertions après la correction du démarrage.

Limites établies :

- aucun `pyproject.toml`, `pytest.ini`, `mypy.ini` ou `ruff.toml` n'a été trouvé ;
- aucune configuration CI sous `.github/` n'a été trouvée ;
- les tests Python sont majoritairement des scripts de régression personnalisés sous `scripts/`, pas une suite unifiée avec collecte, fixtures, marqueurs et couverture ;
- aucun taux de couverture n'est donc mesuré aujourd'hui ;
- le build Next.js ne doit pas être exécuté dans le même arbre pendant `next dev` Turbopack ; le script de build sûr protège déjà ce cas.

## 3. Références officielles retenues

- FastAPI recommande de garder le fichier principal comme point de composition léger et d'organiser les opérations par `APIRouter`, avec préfixes, dépendances et réponses communes au niveau du routeur : [Bigger Applications - Multiple Files](https://fastapi.tiangolo.com/tutorial/bigger-applications/).
- FastAPI recommande le gestionnaire `lifespan` pour les ressources partagées et leur nettoyage : [Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
- Starlette documente l'état typé du lifespan, accessible aux requêtes, et recommande d'exécuter le `TestClient` comme context manager pour tester réellement démarrage et arrêt : [Starlette Lifespan](https://www.starlette.io/lifespan/).
- Next.js ne prescrit pas une structure unique, mais documente la colocation par fonctionnalité/route, les groupes de routes et les frontières `error.js`/`loading.js` : [Next.js Project Structure](https://nextjs.org/docs/app/getting-started/project-structure).
- React précise qu'une dépendance de hook manquante crée une fermeture obsolète et recommande de restructurer l'effet plutôt que de neutraliser le lint : [React exhaustive-deps](https://react.dev/reference/eslint-plugin-react-hooks/lints/exhaustive-deps).
- pytest recommande un `pyproject.toml`, une suite de tests distincte, l'installation éditable et, pour les nouveaux projets, le mode d'import `importlib` : [pytest Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html).

## 4. Options d'architecture à discuter

### Option A — Réécriture ou découpage massif

Principe : déplacer rapidement `main.py`, `tools.py`, `database.py` et les grosses pages dans une nouvelle architecture.

- Sécurité : risque élevé de perdre un garde-fou ou de modifier une autorisation implicite.
- Résilience : risque élevé de rupture sur 346 routes et 344 outils.
- Maintenabilité : cible potentiellement propre, mais historique et responsabilité des régressions difficiles à établir.
- Performance : inconnue ; les imports et initialisations peuvent empirer.
- Coût/dépendance : très élevé, rollback difficile.

Décision proposée : rejeter.

### Option B — Migration incrémentale par façade et contrats

Principe : figer d'abord les contrats, puis extraire un seul domaine à la fois derrière les imports et noms publics existants. `main.py` et `tools.py` restent des façades compatibles pendant la transition.

- Sécurité : garde-fous vérifiés avant et après chaque extraction.
- Résilience : rollback fichier par fichier ; OpenAPI et registres comparés automatiquement.
- Maintenabilité : amélioration progressive, responsabilités mesurables.
- Performance : chaque étape peut mesurer temps de démarrage, latence et mémoire.
- Coût/dépendance : modéré ; aucune nouvelle infrastructure obligatoire.

Décision proposée : retenir.

### Option C — Conserver la structure et ajouter uniquement des contrôles

Principe : ne déplacer aucun code, renforcer lint, logs et tests.

- Sécurité/résilience : meilleur filet immédiat.
- Maintenabilité : la concentration et le couplage continuent d'augmenter.
- Performance : neutre.
- Coût/dépendance : faible à court terme, élevé à long terme.

Décision proposée : utile comme phase zéro, insuffisante comme cible.

## 5. Architecture cible proposée

Ce schéma est une cible de discussion, pas une arborescence déjà autorisée :

```text
backend/
├── app_factory.py            # création FastAPI, middleware, routeurs, handlers
├── lifespan.py               # ressources et superviseur de tâches
├── api/                      # adaptateurs HTTP minces
├── domains/
│   ├── email/                # contrats, service, repository, outils du domaine
│   ├── video/
│   ├── coding/
│   └── ...
├── infrastructure/
│   ├── sqlite/
│   ├── ollama/
│   └── windows/
├── tool_catalog/             # modules par domaine, façade compatible dans tools.py
└── main.py                   # import de create_app(), point d'entrée stable

app/
├── (routes)/                 # pages et layouts
├── _features/                # logique et composants colocables par domaine
└── error.js / loading.js
components/                   # composants réellement partagés
lib/                          # transport, contrats runtime et utilitaires transverses
```

Le nom exact des dossiers importe moins que les règles : une direction claire des dépendances, aucun import du transport HTTP depuis le métier, aucun accès SQLite brut depuis les pages d'API, et une façade stable pendant les migrations.

## 6. Feuille de route avec portes de validation

### Phase 0 — Baseline sans déplacement

1. Capturer un snapshot canonique OpenAPI et le catalogue des outils.
2. Transformer les 37 avertissements ESLint en budget décroissant ; corriger d'abord les hooks e-mail après tests de comportement.
3. Ajouter une politique d'erreur structurée : code public stable, identifiant de corrélation, détail complet uniquement dans le journal.
4. Établir des budgets d'architecture en mode avertissement : taille, couplage sortant, captures silencieuses et appels réseau directs.
5. Ajouter `pyproject.toml` comme point de configuration uniquement après validation des versions de Python et des outils.

Porte : aucune différence OpenAPI, aucun outil ajouté/retiré, 36/36 quick, 28/28 API, 40/40 pages.

### Phase 1 — Supervision du cycle de vie

1. Introduire un conteneur d'état typé pour les ressources partagées.
2. Encapsuler les tâches de fond dans un superviseur avec nom, statut, dernière erreur et arrêt borné.
3. Conserver le même `lifespan` externe et les mêmes intervalles.
4. Tester démarrage, arrêt, annulation et tâche défaillante avec le lifespan réel.

Porte : temps de démarrage non régressé, arrêt propre, aucune tâche orpheline, mêmes endpoints.

### Phase 2 — Premier domaine pilote dans `main.py`

Choix proposé : vidéo avant e-mail. La vidéo est volumineuse mais moins critique pour les données métier et l'envoi sortant. L'e-mail sera extrait après validation de la méthode.

1. Déplacer modèles et routes vidéo dans un `APIRouter` sans déplacer l'implémentation métier.
2. Conserver strictement chemins, méthodes, schémas, statuts et flux SSE.
3. Comparer automatiquement les deux documents OpenAPI.
4. Mesurer et rollback immédiat au moindre écart.

Porte : tests vidéo, API, pages, OpenAPI et smoke réel identiques.

### Phase 3 — Catalogue d'outils par domaine

1. Garder `tools.py` comme façade publique.
2. Extraire un petit domaine à faible risque ; réexporter fonctions, `TOOLS_SPEC` et `TOOLS_REGISTRY` sans changer les noms.
3. Ajouter un test de compatibilité import/identité/schéma.
4. Répéter uniquement après un cycle d'usage réel sans régression.

Porte : 344 noms identiques, schémas identiques, garde-fous identiques, latence de chargement mesurée.

### Phase 4 — Base de données

1. Ajouter une table de migrations versionnées et transactionnelles, adaptée à SQLite ; ne pas imposer un ORM.
2. Capturer sauvegarde, migration montante, test d'idempotence et rollback restauratif.
3. Créer des repositories par domaine derrière les fonctions `database.py` existantes.
4. Interdire progressivement les nouveaux SQL hors repository.

Porte : copie réelle de la base migrée, intégrité vérifiée, ancien code compatible, restauration testée.

### Phase 5 — Frontend par fonctionnalité

1. Corriger les fermetures obsolètes de hooks avec tests, sans ajouter aveuglément des dépendances.
2. Extraire d'abord les composants purs et les hooks de transport des pages les plus longues.
3. Normaliser les réponses réseau avec Zod sur les frontières critiques.
4. Ajouter limites d'erreur et chargement par domaine.
5. Conserver App Router et Turbopack.

Porte : lint sans avertissement de hooks, 40/40 pages, smoke chat, e-mail, voix et avatar.

### Phase 6 — Pipeline reproductible

1. Organiser les tests Python sous une collecte unifiée tout en conservant les scripts `npm run check:*` comme façade Windows.
2. Ajouter typage progressif sur les contrats publics et les services nouvellement touchés.
3. Exécuter CI Windows pour le produit principal et Linux pour les modules réellement portables.
4. Séparer jobs déterministes, intégration locale, Docker, Hyper-V et tests cloud afin qu'une capacité optionnelle n'invalide pas le socle.

Porte : installation propre, `npm ci`, environnement Python reproductible, artefacts de test conservés, aucune dépendance à l'état du poste de développement.

## 7. Décisions nécessaires avant modification structurelle

1. Valider ou rejeter l'Option B.
2. Valider la Phase 0 comme prochain lot sans déplacement.
3. Choisir le domaine pilote : vidéo recommandé ; e-mail possible mais plus risqué.
4. Valider l'introduction future d'un `pyproject.toml` et d'une CI Windows.

Tant que ces décisions ne sont pas prises, seules les corrections de défauts reproductibles et les améliorations de tests sont autorisées.

