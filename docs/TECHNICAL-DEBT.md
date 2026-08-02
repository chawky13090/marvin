# Registre de dette technique de Marvin

État vérifié le 2026-08-02 pour Marvin 2.569.0. Ce registre interdit de présenter le projet
comme « sans dette » lorsque les preuves ne le permettent pas. Une ligne n'est fermée
qu'après correction, test de non-régression et preuve dans `DEVELOPMENT-JOURNAL.md`.

| ID | Sévérité | Domaine | Preuve actuelle | Risque | Traitement et critère de fermeture |
|---|---|---|---|---|---|
| TD-001 | Élevée | Frontend | 6 fichiers JSX dépassent 1 300 lignes; `app/outils/page.jsx` atteint 3 406 lignes | revue difficile, collisions Claude/Codex, régressions d'état | tests de caractérisation puis extraction par domaine; aucun fichier applicatif au-dessus de 1 200 lignes sans dérogation documentée |
| TD-002 | Moyenne | Qualité frontend | ESLint passe avec 37 avertissements préexistants | signaux faibles noyés et effets React fragiles | établir un budget par catégorie, empêcher toute hausse, corriger progressivement jusqu'à zéro |
| TD-003 | Moyenne | Documentation | `CLAUDE.md` contenait encore des faits v2.80 (261 outils) alors que le produit est en v2.569 | décisions prises sur une architecture inexistante | guide courant court, `ARCHITECTURE.md` canonique et test automatique de cohérence livrés en v2.569 |
| TD-004 | Moyenne | Validation | le runner historique s'arrêtait au premier échec | résultats non exécutés présentés implicitement comme couverts | fermé en v2.568 : 237/237 étapes exécutées, rapport atomique et mode `--fail-fast` explicite |
| TD-005 | Faible | Gouvernance | version et journal touchent de nombreux commits | bruit de diff et conflits entre agents | conserver un commit atomique par tranche; étudier une note de version générée sans retirer la traçabilité actuelle |
| TD-006 | Moyenne | Persistance | la matrice globale classe encore la persistance `partial` | restauration hors machine non démontrée sur stockage immuable | exercice de restauration sur support distinct, preuve d'intégrité et procédure portable testée |
| TD-007 | Élevée | Sécurité | la matrice globale garde la fermeture de dette sécurité `partial` | dette résiduelle potentiellement confondue avec un domaine vérifié | fermer ou faire accepter explicitement chaque entrée du registre sécurité; aucun statut `verified` par défaut |

## Règles d'évolution

- Une nouvelle dette reçoit un identifiant, une preuve, un risque, un propriétaire logique et
  un critère objectif de fermeture.
- Une extraction ne compte pas comme amélioration si elle diminue la couverture fonctionnelle,
  le nombre d'outils, la liberté du LLM ou la qualité des résultats.
- Les changements structurels restent sans migration de données autant que possible. Leur
  rollback est la réversion atomique du commit; toute migration persistante exige un rollback
  de données distinct et testé.
- `scripts/test_documentation_baseline.py` bloque les métriques périmées et vérifie que ce
  registre reste référencé par les guides des deux agents.
