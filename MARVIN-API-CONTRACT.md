# Contrat et inventaire API Marvin

Date de référence : 2026-07-29

## État mesuré

Le schéma OpenAPI expose désormais 304 chemins et 366 opérations HTTP, répartis dans
64 familles. Les 366 opérations ont un identifiant unique. La garde LAN documente 362
opérations protégées et leurs erreurs 401/403; les quatre surfaces publiques sont santé,
état de jumelage, jumelage et introspection cryptographique interne. Grâce aux erreurs
communes, 363 opérations ont maintenant un
schéma non vide. Les réponses métier génériques et 71 opérations sans tag restent à
résorber famille par famille.

Le constat critique est objectif :

- 192 mutations ;
- 128 mutations avec corps de requête ;
- 363 opérations avec une erreur 4xx documentée ;
- 362 opérations protégées par le contrat de session LAN ;
- 0 mutation déclarant une clé d'idempotence.

La garde globale fournit l'identité réseau, mais pas encore l'autorisation fine par capacité.
La promotion suivra donc l'ordre : transport HTTPS LAN, autorisation par capacité,
idempotence des mutations à effet, puis modèles de réponse métier explicites. Chaque famille
garde ses routes pendant la migration.

## Gate

`scripts/test_api_contract_inventory.py` importe l'application sans démarrer le lifespan,
analyse son OpenAPI et refuse doublons méthode/chemin, `operationId` dupliqué ou absent, route
non taguée et dérive de la baseline. Toute évolution modifie le contrat et sa preuve dans le
même commit.

<!-- api-contract-baseline
paths|304
operations|366
mutations|192
typed_responses|363
documented_errors|363
secured|362
idempotent_mutations|0
request_bodies|128
untagged|71
missing_operation_ids|0
-->

## Rollback

Cette tranche n'intercepte aucune requête et ne modifie aucune route. Rollback par réversion
atomique du commit v2.464. Le retrait du gate ne change ni donnée ni schéma.
