# Forge Windows Operator — contrat v1.1

Cette correction versionnée remplace v1 avant toute baseline. Les artefacts v1 restent
immuables. Elle sépare l'allocation locale observée, la capacité Cloud déclarée et la
rétention Cloud mesurée fonctionnellement.

## Précondition locale

- Le profil matériel est calculé à partir du modèle exact et épinglé dans la campagne.
- Le cache KV est estimé depuis les métadonnées d'attention. Une architecture hybride est
  signalée et ne peut pas être certifiée par la seule formule.
- `/api/ps` prouve ensuite le contexte, `size`, `size_vram` et la résidence GPU.
- L'environnement du script de capture est diagnostique, jamais une preuve du service.

## Précondition Cloud

- `/api/show` prouve uniquement la capacité maximale déclarée du tag exact.
- Aucun `num_ctx` client ne doit réduire le contexte Cloud.
- L'allocation fournisseur étant invisible, un test de rétention long contexte est requis.

## Rollback

Une réversion atomique restaure le contrat v1. Les preuves v1 et v1.1 ne sont jamais
réécrites ; une nouvelle mesure crée un nouveau dossier de campagne.
