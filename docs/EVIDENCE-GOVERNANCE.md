# Gouvernance des preuves Marvin

## Source de vérité

`benchmarks/evidence-governance/v1/supersession-registry.json` est l'index canonique des
preuves remplacées. Il ne modifie jamais un artefact historique. Une identité de preuve est
le couple chemin relatif au dépôt + SHA-256 exact.

La supersession est déclarée par sujet. Un fichier d'analyse peut donc rester courant pour
certains contrats et être remplacé pour d'autres. Chaque sujet possède exactement une révision
`current`; toute autre révision rejoint cette révision par une chaîne unique, sans cycle ni
convergence concurrente.

## Inventaire E0-E7 courant

`benchmarks/tool-evidence/v1.2/inventory.json` remplace les inventaires v1 et v1.1 sans les
réécrire. Il lit SQLite en lecture seule et n'accorde E7 qu'à partir d'un verdict terminal
explicite référencé par chemin et empreinte. Deux couples sont actuellement vérifiés :

- `bulk_rename:preview`, classe N ;
- `bulk_rename:apply`, classe R sur cinq cycles isolés.

Les 434 autres couples restent `unassessed` en E7. Une supersession de contrat ou une réussite
SQLite ne peut jamais les promouvoir.

## Reproduction

```powershell
# Target: Windows 11
# Shell/CLI: PowerShell 5.1+
# Privileges: Utilisateur
# Objective: Régénérer l'inventaire courant puis valider toutes les chaînes de preuve

$env:PYTHONIOENCODING = 'utf-8'
.\backend\.venv\Scripts\python.exe scripts\build_evidence_supersession_registry.py
.\backend\.venv\Scripts\python.exe scripts\test_evidence_supersession_registry.py
```

La génération refuse toute divergence entre une preuve historique et son blob Git au commit
de pré-enregistrement. Aucun outil métier, runtime Marvin ou écriture dans SQLite n'est utilisé.

## Rollback

Révertir atomiquement les commits v2.650, puis redémarrer Marvin. Les preuves historiques,
la base et les données utilisateur ne nécessitent aucune restauration. Les fichiers v1.2 et le
registre externe peuvent disparaître ensemble; les versions v1/v1.1 restent intactes.
