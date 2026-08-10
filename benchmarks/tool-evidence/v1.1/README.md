# Inventaire de preuve des outils Marvin v1.1

Cette version corrige sans réécrire v1 deux ambiguïtés de mesure :

- un niveau non évaluable vaut `null` (`unassessed`), jamais `false` ;
- la première vague B cible les actions dangereuses visibles du LLM sans rollback E7
  explicitement vérifié. Les outils totalement vierges forment la vague suivante.

E5 reste `unassessed` : l'ancien schéma SQLite ne permet pas d'attribuer de façon fiable une
exécution orpheline à un automatisme réel plutôt qu'à Forge ou à un test. Les compteurs
d'activité ne sont donc ni perdus ni transformés en preuve.

La campagne reste verrouillée. `null` n'autorise jamais une action et ne vaut jamais rollback.
Chaque action exige fixture isolée, oracle indépendant, teardown et restauration rejouée.

## Reproduction

```powershell
$env:PYTHONIOENCODING = 'utf-8'
.\backend\.venv\Scripts\python.exe scripts\build_tool_evidence_inventory.py
.\backend\.venv\Scripts\python.exe scripts\build_tool_evidence_campaign_b.py
```

Le script ouvre SQLite en lecture seule et publie les artefacts atomiquement. V1 reste
immuable ; v1.1 possède ses propres empreintes et son propre contrat.
