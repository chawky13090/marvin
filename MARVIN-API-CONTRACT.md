# Contrat et inventaire API Marvin

Date de référence : 2026-07-29

## État mesuré

Le schéma OpenAPI expose 300 chemins et 362 opérations HTTP, répartis dans 63 familles.
Les 362 opérations ont un identifiant unique. 273 ont un schéma de réponse non vide; 89
restent génériques et 71 opérations ne possèdent aucun tag. Ces lacunes devront être
résorbées famille par famille.

Le constat critique est objectif :

- 189 mutations ;
- 127 mutations avec corps de requête ;
- 0 réponse d'erreur 4xx/5xx documentée hors validation automatique 422 ;
- 0 opération avec sécurité OpenAPI ;
- 0 mutation déclarant une clé d'idempotence.

Ces zéros ne signifient pas que toutes les implémentations sont dépourvues de validation ou
de contrôles internes. Ils signifient que le contrat public ne les garantit pas et confirme
la dette SEC-001. La promotion suivra l'ordre : identité/session locale, autorisation par
capacité, erreurs communes expurgées, idempotence des mutations à effet, puis modèles de
réponse explicites. Chaque famille garde ses routes pendant la migration.

## Gate

`scripts/test_api_contract_inventory.py` importe l'application sans démarrer le lifespan,
analyse son OpenAPI et refuse doublons méthode/chemin, `operationId` dupliqué ou absent, route
non taguée et dérive de la baseline. Toute évolution modifie le contrat et sa preuve dans le
même commit.

<!-- api-contract-baseline
paths|300
operations|362
mutations|189
typed_responses|273
documented_errors|0
secured|0
idempotent_mutations|0
request_bodies|127
untagged|71
missing_operation_ids|0
-->

## Rollback

Cette tranche n'intercepte aucune requête et ne modifie aucune route. Rollback par réversion
atomique du commit v2.464. Le retrait du gate ne change ni donnée ni schéma.
