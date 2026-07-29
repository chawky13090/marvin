# Migration des consommateurs vers le harness universel

Date de référence : 2026-07-29
Version : 2.446.0
Source de vérité exécutable : `scripts/test_tool_consumer_inventory.py`

## Contrat cible

Un consommateur HTTP, worker ou service ne doit pas appeler directement un exécuteur dans
`TOOLS_REGISTRY`. Il passe par `tool_runtime.execute`, qui compose le gateway commun :

1. validation du schéma ;
2. niveau d'autorisation fail-closed ;
3. confirmation des actions dangereuses ;
4. reçu idempotent ;
5. capture d'exception expurgée ;
6. contrat de résultat ;
7. historique d'exécution ;
8. audit corrélé.

Le Runner conserve son pipeline spécialisé `agent_tool_batch`/`agent_execution`, qui applique
les mêmes invariants et ajoute les preuves Mission OS. Son unique accès au registre injecte
le Council comme dépendance et n'exécute pas directement un choix du modèle.

## État mesuré

L'agenda, le domaine proactif, les orchestrateurs et les API/workers e-mail sont migrés.
Les appels parallèles sont bornés, chaque étape de workflow possède une identité de tentative,
un cycle cron possède une clé de rejeu stable et une automatisation e-mail planifiée possède
une clé par minute. L'inventaire détecte les indexations directes, les alias locaux et les
appels `.get`; il a corrigé le précédent comptage incomplet de 48.
Les accès directs historiques restants sont temporairement bornés :

| Composant | Appels directs | Traitement prévu |
|---|---:|---|
| `api/system_tools.py` | 25 | migrer par groupes lecture/mutation avec confirmations UI |
| `api/content.py` | 9 | préserver upload, limites et réponses historiques |
| `api/documents.py` | 7 | préserver erreurs métier et artefacts |
| `agent.py` | 1 | injection Council, pas un contournement d'exécution |

Le gate AST échoue si un fichier ou un accès direct apparaît sans mise à jour explicite. La
valeur 42 est un plafond transitoire, jamais une cible : chaque tranche doit la réduire.

## Sécurité, logs et rollback

Le runtime n'enregistre aucun argument supplémentaire. Il réutilise l'expurgation, la
corrélation et la rétention existantes. Une panne d'audit ou d'historique est signalée dans
`observation_errors` sans rejouer une action déjà effectuée. Les suppressions agenda ne sont
confirmées que par la route DELETE issue du geste UI; le LLM reste soumis à confirmation.

Chaque migration est un commit atomique sans changement de schéma. Rollback :
`git revert <commit>`, redémarrage backend, tests du runtime, de la famille migrée, architecture
et smoke API.
