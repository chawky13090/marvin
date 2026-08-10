# Inventaire de preuve des outils Marvin v1

Cet inventaire mesure la surface réellement prouvée du catalogue sans exécuter d'outil.
L'unité est `outil + action` lorsqu'un champ `action` possède une énumération, sinon l'outil.

## Niveaux

- E0 : catalogue ;
- E1 : schéma et exécuteur dans le harnais ;
- E2 : référence de test automatisé identifiée ;
- E3 : intégration isolée explicitement prouvée ;
- E4 : E2E avec oracle d'état indépendant ;
- E5 : automatisme réel attribué et réussi ;
- E6 : message utilisateur persistant lié à une exécution réussie ;
- E7 : résultat métier et rollback explicitement vérifiés.

Les niveaux ne sont jamais déduits d'un simple code retour. En particulier, `success=1` dans
`tool_executions` ne prouve ni la postcondition métier ni le rollback. Les exécutions dont la
conversation a disparu sont classées `orphan_or_ephemeral` et ne comptent jamais comme usage
humain. Cette catégorie regroupe historiquement Forge, des tests et d'autres contextes
éphémères que l'ancien schéma ne permet pas de distinguer.

## Reproduction

Marvin doit être arrêté pour une empreinte stable de la base :

```powershell
$env:PYTHONIOENCODING = 'utf-8'
.\backend\.venv\Scripts\python.exe scripts\build_tool_evidence_inventory.py
```

Le script ouvre SQLite en lecture seule et publie `inventory.json` atomiquement. Il ne modifie
ni le routage, ni le catalogue, ni les données. Un changement de schéma ou de sémantique
exige une nouvelle version de l'inventaire ; l'artefact v1 reste immuable.
