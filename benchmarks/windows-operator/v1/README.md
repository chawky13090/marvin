# Forge Windows Operator — contrat v1

Ce dossier fige la méthodologie avant la première baseline. Il ne contient encore ni
`windows_task`, ni résultat de campagne, ni corpus prétendument finalisé.

## Invariants

- Une campagne est invalide sans preuve de contexte Ollama correspondant au modèle exact.
- Le modèle, le catalogue d'outils, le commit, le contexte et les paramètres sont figés.
- Chaque répétition appelle un fixture de code typé pour rétablir son état initial.
- Le teardown s'exécute dans un bloc `finally`, y compris après échec de l'agent.
- Un run interrompu est rejeté; il n'est jamais repris comme s'il était indépendant.
- L'oracle est développé hors du vérificateur de production et ne partage pas sa logique.
- Le corpus holdout n'est pas utilisé pour corriger le moteur.
- `computer_control` et `windows_task` ne sont jamais visibles ensemble en production.

Les fixtures et oracles seront enregistrés par identifiant dans le runner Forge. Le JSON
d'un scénario ne peut contenir ni commande PowerShell arbitraire, ni module Python dynamique,
ni chemin d'exécutable fourni par le modèle. Cette frontière empêche un corpus modifié de
devenir un canal d'exécution.

## Preuve de contexte

Après préchauffage explicite du modèle épinglé, capturer la preuve :

```powershell
# Target: Windows 11
# Shell/CLI: PowerShell 7 ou Windows PowerShell 5.1
# Privileges: Utilisateur
# Objective: Capturer le contexte réellement disponible avant une campagne

backend\.venv\Scripts\python.exe scripts\capture-ollama-context-evidence.py `
  --model "MODELE_EPINGLE" `
  --output "benchmarks/windows-operator/campaigns/CAMPAGNE/context-evidence.json"
```

Le script n'effectue aucune inférence. Un modèle local absent de `/api/ps` produit
`deferred` et bloque la campagne. Pour un modèle Cloud, la capacité du tag exact est lue via
`/api/show` et qualifiée selon la garantie de contexte maximal d'Ollama Cloud.

## Rollback

Avant toute donnée de campagne, une réversion atomique du commit retire ce contrat et le
diagnostic Doctor. Les futurs résultats sous `campaigns/` seront des artefacts immuables : ils
ne devront jamais être réécrits pour faire passer un candidat.
