# Gouvernance des données personnelles dans les preuves Marvin

## Décision

Les quatorze flux persistants sont classifiés par `backend/privacy_inventory.py`. Le registre
déclare les champs de contenu libre, les sélecteurs stables, le mode d'export et la stratégie
d'effacement. Il ne lit ni ne publie le contenu des preuves.

Un tombstone append-only n'est pas considéré comme un effacement : le contenu initial reste
présent. Une réécriture directe non compensée est également interdite car elle invalide la
chaîne sans preuve. La cible pour les flux `rechain_required` est donc :

1. sélectionner par identifiant exact, jamais par recherche floue dans le texte ;
2. vérifier la chaîne et produire son empreinte avant opération ;
3. créer une sauvegarde chiffrée bornée et restaurable ;
4. réécrire atomiquement les lignes conservées et recalculer la chaîne ;
5. vérifier schéma, cardinalité, empreinte et absence du sélecteur ;
6. conserver un reçu sans contenu personnel avec empreintes avant/après et compteurs ;
7. restaurer automatiquement la sauvegarde si une validation échoue.

Les journaux techniques bornés utilisent leur rétention existante. Les flux liés à un
propriétaire privilégient la suppression confirmée de l'objet complet. L'effacement sélectif
est disponible hors ligne depuis v2.588, mais SEC-010 reste `MITIGATED` tant que le cycle de
finalisation du rollback temporaire n'est pas automatisé et vérifié dans l'interface.

## Export d'accès disponible

Huit registres racine (`mission_os`, `forge`, les trois flux `arena_*`, `model_market`,
`research_swarm`, `truth_ledger`) acceptent uniquement les sélecteurs exacts déclarés par
l'inventaire. Le contenu libre n'est jamais un sélecteur.

```text
# Target: Windows 11, Marvin 2.588+
# Shell/CLI: PowerShell 5.1 ou PowerShell 7
# Privileges: utilisateur propriétaire des données Marvin
# Objective: exporter les preuves d'une conversation dans un bundle chiffré

backend\.venv\Scripts\python.exe scripts\export-privacy-data.py truth_ledger conversation_id C:\chemin\export.mrvprivacy
```

La phrase secrète est demandée deux fois par saisie masquée. Elle n'est jamais placée dans la
ligne de commande, l'environnement ou l'audit. Le fichier n'est publié qu'après déchiffrement
de contrôle et comparaison exacte. Le résultat public contient uniquement registre,
sélecteur, compteurs, taille et empreinte; jamais la valeur sélectionnée.

## Effacement compensé disponible hors ligne

L'effacement n'est pas exposé à un LLM ni à une route HTTP. Le backend doit être arrêté, la
confirmation `--confirmed` explicite et la valeur exacte est saisie de manière masquée.

```text
# Target: Windows 11, Marvin 2.588+
# Shell/CLI: PowerShell 5.1 ou PowerShell 7
# Privileges: utilisateur propriétaire des données Marvin
# Objective: effacer une conversation du Truth Ledger avec rollback chiffré

backend\.venv\Scripts\python.exe scripts\erase-privacy-data.py truth_ledger conversation_id C:\chemin\rollback.mrvprivacy --confirmed
```

Le résultat signale `rollback_contains_erased_data=true` et `finalization_required=true`.
Tant que ce bundle existe et que sa phrase secrète est conservée, les données restent
récupérables : le droit d'effacement n'est donc pas considéré comme définitivement finalisé.

```text
# Target: Windows 11, Marvin 2.588+
# Shell/CLI: PowerShell 5.1 ou PowerShell 7
# Privileges: utilisateur propriétaire des données Marvin
# Objective: restaurer exactement le registre avant effacement

backend\.venv\Scripts\python.exe scripts\restore-privacy-data.py truth_ledger C:\chemin\rollback.mrvprivacy --confirmed
```

Références : [articles 15 à 19 du RGPD publiés par la CNIL](https://www.cnil.fr/fr/reglement-europeen-protection-donnees/chapitre3),
[guide CNIL du droit à l'effacement](https://www.cnil.fr/fr/comprendre-mes-droits/le-droit-leffacement-supprimer-vos-donnees-en-ligne)
et [modèle Event Sourcing de Microsoft](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing). Un motif légal de conservation doit être décidé par
le responsable du traitement, jamais inventé automatiquement par Marvin.

## Rollback

Le rollback fonctionnel est le bundle chiffré créé avant chaque effacement et vérifié avant
réécriture. Le rollback du code est la réversion atomique du commit v2.588.
