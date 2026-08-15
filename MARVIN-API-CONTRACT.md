# Contrat et inventaire API Marvin

Date de référence : 2026-08-13

## État mesuré

Le schéma OpenAPI expose désormais 329 chemins et 395 opérations HTTP, répartis dans
67 familles. Les 395 opérations ont un identifiant unique. La garde LAN documente 391
opérations protégées, leur capacité et leurs erreurs 401/403; les quatre surfaces publiques sont santé,
état de jumelage, jumelage et introspection cryptographique interne. Grâce aux erreurs
communes, 393 opérations ont maintenant un
schéma non vide. Les réponses métier génériques et 71 opérations sans tag restent à
résorber famille par famille.

Le constat critique est objectif :

- 207 mutations ;
- 139 mutations avec corps de requête ;
- 392 opérations avec une erreur 4xx ou 5xx documentée ;
- 391 opérations protégées par le contrat de session LAN ;
- 391 opérations déclarant une capacité serveur contrôlée à chaque requête ;
- 9 mutations critiques déclarant une clé d'idempotence UUID optionnelle.

La garde globale fournit l'identité réseau et l'autorisation par capacité.
La promotion suivra donc l'ordre : transport HTTPS LAN,
extension progressive de l'idempotence selon la sémantique métier, puis modèles de réponse
métier explicites. Chaque famille
garde ses routes pendant la migration.

## Gate

`scripts/test_api_contract_inventory.py` importe l'application sans démarrer le lifespan,
analyse son OpenAPI et refuse doublons méthode/chemin, `operationId` dupliqué ou absent et
dérive de la baseline. Les 71 opérations sans tag restent mesurées comme dette explicite.
Toute évolution modifie le contrat et sa preuve dans le
même commit.

<!-- api-contract-baseline
paths|329
operations|395
mutations|207
typed_responses|393
documented_errors|392
secured|391
capability_declared|391
idempotent_mutations|9
request_bodies|139
untagged|71
missing_operation_ids|0
-->

## Rollback

Cette tranche n'intercepte aucune requête et ne modifie aucune route. La baseline v2.647
réconcilie le contrat avec les routes ajoutées depuis v2.464 et remet le test dans le gate.
Rollback par réversion atomique du commit v2.647. Le retrait du gate ne change ni donnée ni
schéma.
