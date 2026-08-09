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

## Verrou runtime exécutoire

Avant une campagne, créer le verrou depuis le profil local certifié :

```powershell
# Target: Windows 11
# Shell/CLI: PowerShell 5.1 ou 7
# Privileges: Utilisateur Marvin
# Objective: Verrouiller le modèle, le digest, Ollama, le contexte et le cache KV

& .\backend\.venv\Scripts\python.exe .\scripts\forge-runtime-lock.py create `
  --campaign-id windows-operator-baseline
```

La commande retourne le chemin et la variable `MARVIN_FORGE_RUNTIME_LOCK` à exporter dans
le processus de campagne. L'admission du Runner échoue fermée si le modèle exact, son digest,
la version Ollama, le profil, le contexte, le cache KV ou le parallélisme dérivent. Le verrou
expire après 24 heures par défaut. Une exécution interrompue ou en dérive est rejetée, jamais
comptée dans les métriques.

## Corpus et couches de mesure

`corpus-manifest.json` fige par SHA-256 les 120 intentions et les 15 scénarios avant toute
implémentation de `windows_task`. Le holdout (40 intentions et 5 scénarios) reste fermé
pendant le développement. Les campagnes normatives sont séparées :

- `routing-development.json` : 240 décisions, trois répétitions par intention ;
- `executor-development.json` : 50 exécutions directes avec oracle indépendant ;
- `e2e-development.json` : 50 parcours FastAPI complets avec modèle et Cortex épinglés.

Une réussite de `tool_search` n'est jamais une affirmation de succès métier. Le
classificateur bout-en-bout ne qualifie un faux succès que lorsque l'outil cible annonce
l'achèvement et que l'oracle indépendant constate l'échec. Les artefacts `invalid-*`
documentent les campagnes interrompues ou une méthodologie rejetée; ils sont exclus des
comparaisons et des seuils.

## Rollback

Une réversion atomique restaure le contrat v1. Les preuves v1 et v1.1 ne sont jamais
réécrites ; une nouvelle mesure crée un nouveau dossier de campagne.
