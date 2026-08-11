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

## Taxonomie E7 gelée

`e7-taxonomy-policy.json` définit R (restauration exacte), C (compensation avec perte
mesurée), I (irréversibilité intrinsèque confinée), N (aucune mutation) et P (effet dépendant
du payload). `e7-classification.json` couvre exactement les 36 couples de première vague.
`e7-freeze-manifest.json` lie par SHA-256 politique, classification et candidats. P impose un
nouveau gel du scénario concret en R/C/I/N et ne peut jamais valider E7 globalement.

## Strates de fixtures et harnais H7

`fixture-strata-policy.json` sépare les 36 couples en 22 couples R/C/I/N directement
spécifiables, 6 couples P à scénarios finis et 8 exécuteurs arbitraires. Ces derniers ne sont
pas certifiés par une liste nécessairement incomplète d'effets. `h7-harness-policy.json`
pré-enregistre une preuve distincte H7 portant sur le harnais d'autorisation et d'exécution.
H7 ne modifie jamais E7. `h7-adversarial-corpus.json` contient uniquement 30 cas abstraits,
dont le refus absolu d'une commande catastrophique malgré l'accès Complet et une approbation
valide, ainsi que le plafond Auto de risque 3 sur une action non élevée :
aucune commande, cible, donnée utilisateur ou charge utile exécutable. Le manifeste SHA-256
verrouille ces sources avant toute conception de fixture ou exécution de harnais.
# Contrats directs gelés

`direct-fixture-contracts.json` décrit les 22 couples directs sans les exécuter. Le setup,
l'oracle et la récupération appartiennent exclusivement au harnais de fixtures et ne peuvent
ni appeler un outil public Marvin, ni réutiliser le système sous test. Le pilote de
`direct-fixture-pilot.json` couvre six surfaces distinctes et les classes N, R, C et I.
`direct-fixture-freeze-manifest.json` gèle les sources et contrats avant l'implémentation des
fixtures. Toute exécution d'outil et toute exécution sur l'hôte restent interdites.

`pilot-fixture-harness-manifest.json` gèle l'implémentation symbolique des six pilotes. Le
paquet `scripts/e7_fixture_harness` n'importe aucun module produit, s'exécute sous `python -I`
avec une liste blanche `meta_path` et bloque `exec/compile` par audit local. L'audit hook reste
strictement confiné au sous-processus. Les canaris positif et négatifs sont obligatoires.

La frontière de processus v2.617 surveille les événements d'audit de spawn. Les plans
`winget_uninstall` et `pc_process_kill` portent une politique positive d'exécutables. Un enfant
Python passe obligatoirement par le bootstrap `-I`, qui réinstalle la garde avant tout module
de fixture. Un spawn non déclaré ou `python -c/-m` échoue fermé. Aucun spawn métier n'est
autorisé par le manifeste : seuls les canaris inoffensifs du harnais sont exécutés.
