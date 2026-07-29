# Marvin Research Engine v3

Date : 2026-07-29
Version : 2.486.0
État : actif par défaut, moteur v2 conservé comme repli

## Objectif et périmètre

Research Engine v3 remplace l'exécution fixe du Research Swarm par une recherche
adaptative exclusivement alimentée par l'instance SearXNG configurée. Les façades
`ai_research_swarm` et `/api/model-market/swarm/*` restent compatibles.

Le moteur couvre :

- contrat explicite et budgets bornés ;
- portefeuille initial de requêtes complémentaires ;
- analyse des lacunes et reformulation multi-passes ;
- filtres SearXNG de langue et de fraîcheur ;
- lecture publique protégée contre SSRF ;
- canonicalisation, déduplication exacte et quasi-identique ;
- limitation de concentration par domaine ;
- cinq rôles Ollama Cloud spécialisés ;
- audit séparé puis réparation bornée des citations ;
- gate Research Forge et preuve durable dans le registre Swarm existant ;
- progression SSE, annulation, checkpoint, reprise et réorientation en cours d'exécution ;
- restitution lisible et exports Markdown, JSON, DOCX et PDF.

## Flux

```text
Demande
  -> ResearchContract
  -> requêtes discovery/primary/counterevidence/freshness/implementation/verification
  -> SearXNG
  -> lecture anti-SSRF
  -> SourceIndex
  -> analyse des lacunes
  -> nouvelles requêtes bornées
  -> cinq analyses spécialisées
  -> audit des affirmations
  -> synthèse citée
  -> Research Forge
  -> réparation éventuelle
  -> registre de preuve et interface
```

## Contrats et limites

| Profil | Requêtes max. | Pages max. | Passes max. | Durée max. |
|---|---:|---:|---:|---:|
| quick | 6 | 18 | 2 | 180 s |
| deep | 18 | 60 | 6 | 900 s |
| exhaustive | 36 | 120 | 10 | 1 800 s |

Les limites utilisateur ne peuvent pas dépasser le profil exhaustif. Une recherche
est annulable ; les retries réseau restent ceux des transports partagés existants et
ne sont jamais infinis.

## Sécurité et confidentialité

- SearXNG reste l'unique fournisseur de résultats.
- Les pages utilisent `outbound_http.fetch_public` : validation des destinations,
  redirections et tailles avant lecture.
- Chaque extrait Web est marqué non fiable et analysé par le garde d'injection
  `evidence_fabric`.
- Les contenus observés ne peuvent ni appeler un outil ni modifier le contrat.
- Le mode Hyper local bloque la recherche Cloud. Les données sensibles restent
  bloquées hors Ultra débridé.
- Aucun prompt, texte de page ou rapport n'est ajouté aux logs techniques.
- Le registre existant est un `evaluation_ledger`; sa conservation n'est pas
  gouvernée par la rotation des logs techniques.
- Les erreurs persistées restent limitées à leur classe ou à un message métier borné.

Dette résiduelle : le gate lexical Research Forge mesure la présence et la validité
structurelle des citations. La vérification sémantique repose encore sur les rôles Cloud
et doit être complétée par un corpus humain de référence avant toute affirmation de
supériorité face à un service tiers.

## Observabilité

La progression publie uniquement :

- étape et message métier ;
- compte de requêtes ;
- sources et domaines uniques ;
- couverture des axes ;
- statut du gate et persistance de la preuve.

Le checkpoint conserve la trajectoire et les URL publiques retenues, sans texte de page.
Après redémarrage, la reprise relit ces URL sous les mêmes contrôles réseau et évite de
réexécuter les requêtes de découverte déjà terminées. Une orientation utilisateur est
bornée à 500 caractères et injectée comme requête prioritaire au prochain tour.

Elle exclut les requêtes complètes, contenus de pages, prompts, secrets et réponses
intermédiaires. Les incidents réseau/modèle continuent d'utiliser les journaux
structurés existants et leur politique de rétention.

## Validation

```text
# Target: Windows 11
# Shell/CLI: PowerShell 5.1
# Privileges: Utilisateur
# Objective: Valider le moteur sans appel Cloud réel

backend\.venv\Scripts\python.exe scripts\test_research_engine_v3.py
backend\.venv\Scripts\python.exe scripts\test_model_market.py
backend\.venv\Scripts\python.exe scripts\check_architecture.py
backend\.venv\Scripts\python.exe scripts\test_api_contract_inventory.py
npx eslint app/market/page.jsx components/chat/MessageBubble.jsx
```

Le test v3 couvre contrat, entrées invalides, budgets, URL, doublons, sources,
citations, exports DOCX/PDF et une exécution adaptative complète avec transports simulés.

## Rollback

Aucune migration de schéma ou de donnée n'est introduite.

Rollback opérationnel immédiat :

```text
research_engine_v3_enabled = false
```

ou passage de `engine_version="v2"` à la façade. Les runs v3 restent lisibles dans
le registre historique et ne sont ni transformés ni supprimés.

Rollback du code :

1. arrêter le backend ;
2. réverter atomiquement le commit 2.486 ;
3. redémarrer le backend et le frontend ;
4. exécuter `scripts/test_model_market.py` ;
5. vérifier `/api/health` et une recherche v2.

Comme aucune donnée n'est migrée, la réversion Git suffit.
