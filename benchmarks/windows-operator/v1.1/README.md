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

## Rollback

Une réversion atomique restaure le contrat v1. Les preuves v1 et v1.1 ne sont jamais
réécrites ; une nouvelle mesure crée un nouveau dossier de campagne.
