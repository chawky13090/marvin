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
reste désactivé tant que le mécanisme compensé ci-dessus n'est pas livré et testé; SEC-010
reste donc `MITIGATED`, pas `VERIFIED`.

Références : [articles 15 à 19 du RGPD publiés par la CNIL](https://www.cnil.fr/fr/reglement-europeen-protection-donnees/chapitre3),
[guide CNIL du droit à l'effacement](https://www.cnil.fr/fr/comprendre-mes-droits/le-droit-leffacement-supprimer-vos-donnees-en-ligne)
et [modèle Event Sourcing de Microsoft](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing). Un motif légal de conservation doit être décidé par
le responsable du traitement, jamais inventé automatiquement par Marvin.

## Rollback

Cette tranche n'altère aucune donnée. Son rollback est la réversion atomique du commit v2.586.
