# Idempotence des actions Marvin

Date de référence : 2026-07-29
Version : 2.469.0

## Contrat

Les mutations suivantes acceptent le header optionnel `Idempotency-Key`, au format UUID.
Sans header, le comportement historique reste inchangé. Avec le header, l'exécution passe
par le registre transactionnel `action_receipts` :

- `/api/tools` et `/api/mcp/execute` ;
- `/api/email/send` et `/api/events` ;
- `/api/backups/restore` et `/api/workflows/{id}/run` ;
- `/api/coding/projects` et `/api/vm-lab/install`.

- première requête : réservation SQLite atomique puis exécution ;
- retry identique terminé : réponse précédente sans reproduire l'effet ;
- retry identique encore actif : HTTP 409 ;
- reprise après interruption dont l'effet est inconnu : HTTP 409 et aucun rejeu ;
- même clé avec outil, conversation ou arguments différents : HTTP 422 ;
- clé syntaxiquement invalide : HTTP 422 avant le Runner.

Le header de réponse `Idempotency-Replayed` indique `true` pour un résultat relu et `false`
pour une première exécution ou une action encore active. Le frontend génère automatiquement
une clé UUID pour ces appels directs. Un client qui effectue son
propre retry doit réutiliser explicitement la même clé.

## Choix d'architecture

Deux approches ont été comparées :

1. ajouter un cache HTTP séparé, simple mais créant une seconde source de vérité ;
2. étendre le registre des reçus déjà utilisé par le Runner et le chat.

La seconde est retenue. La corrélation technique `request_id` et la clé client restent
distinctes. La clé brute n'est jamais stockée : son empreinte SHA-256 devient la clé primaire
du reçu. Le fingerprint couvre conversation, outil et arguments canoniques. Les résultats
persistés sont expurgés récursivement avant tout replay.

Cette conception suit Google AIP-155 et le comportement AWS : un retry identique relit le
succès antérieur, tandis qu'une même clé associée à d'autres paramètres échoue. Les codes
409/422 suivent le projet IETF HTTPAPI `Idempotency-Key`; ce document reste un Internet-Draft,
pas encore une RFC.

## Persistance, logs et limites

Les reçus vivent dans la base SQLite autoritative existante. Ils ne conservent ni arguments
bruts ni clé client brute; uniquement empreintes, identité d'outil, statut, corrélation et
résultat expurgé. Aucune nouvelle ligne de log n'est créée. Une panne d'écriture après effet
est signalée par un incident opaque et interdit de présenter le reçu comme persisté.
Une exception pendant un effet externe ferme le reçu en `unknown` : Marvin préfère une
vérification humaine ou métier à un second envoi, workflow ou déploiement.

Les reçus sont actuellement conservés avec la base Marvin. Une politique de compaction ne
sera ajoutée qu'après la comparaison demandée entre la persistance actuelle, LangGraph,
MARVA à identifier et les autres stores agentiques : supprimer trop tôt un reçu pourrait
réautoriser un effet ancien. Cette limite est donc explicite et mesurable, pas masquée.

## Rollback

Réversion atomique des commits v2.467 à v2.469. Aucun schéma ni contenu existant n'est migré.
Les reçus créés utilisent la table historique et restent lisibles après réversion;
ils deviennent simplement inertes pour les headers HTTP.
