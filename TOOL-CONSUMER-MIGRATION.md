# Migration des consommateurs vers le harness universel

Date de référence : 2026-07-29
Version : 2.448.0
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

Tous les consommateurs sont migrés, y compris les 25 appels système et l'escalade Council
interne.
Les appels parallèles sont bornés, chaque étape de workflow possède une identité de tentative,
un cycle cron possède une clé de rejeu stable et une automatisation e-mail planifiée possède
une clé par minute. L'inventaire détecte les indexations directes, les alias locaux et les
appels `.get`; il a corrigé le précédent comptage incomplet de 48.
Le gate AST échoue désormais dès qu'un accès direct réapparaît : la dette mesurée est zéro.
Le registre reste la table de composition des 344 exécuteurs, mais aucun consommateur HTTP,
worker, workflow, cron ou branche interne ne l'indexe pour exécuter un outil hors harness.

Les outils Windows mixtes utilisent une politique par action. `status`, `get` et `list`
restent des lectures disponibles en mode Sécurisé. Toute autre action échoue fermée dans ce
mode et exige en Standard une confirmation provenant du canal UI, jamais des arguments du
modèle ou d'un client.

## Sécurité, logs et rollback

Le runtime n'enregistre aucun argument supplémentaire. Il réutilise l'expurgation, la
corrélation et la rétention existantes. Une panne d'audit ou d'historique est signalée dans
`observation_errors` sans rejouer une action déjà effectuée. Les suppressions agenda ne sont
confirmées que par la route DELETE issue du geste UI; le LLM reste soumis à confirmation.

Chaque migration est un commit atomique sans changement de schéma. Rollback :
`git revert <commit>`, redémarrage backend, tests du runtime, de la famille migrée, architecture
et smoke API.
