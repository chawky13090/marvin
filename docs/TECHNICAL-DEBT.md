# Registre de dette technique de Marvin

État vérifié le 2026-08-02 pour Marvin 2.582.0. Ce registre interdit de présenter le projet
comme « sans dette » lorsque les preuves ne le permettent pas. Une ligne n'est fermée
qu'après correction, test de non-régression et preuve dans `DEVELOPMENT-JOURNAL.md`.

| ID | Sévérité | Domaine | Preuve actuelle | Risque | Traitement et critère de fermeture |
|---|---|---|---|---|---|
| TD-001 | Fermée | Frontend | zéro fichier JavaScript/JSX au-dessus de 1 200 lignes en v2.578; `app/emails/page.jsx` est passé de 1 321 à 1 181 lignes après les cinq extractions précédentes | risque historique de revue difficile et collisions Claude/Codex | fermé par caractérisations préalables, baseline 121 sources sans exception, builds et gates exhaustifs; toute réintroduction est bloquée |
| TD-002 | Moyenne | Qualité frontend | ESLint passe avec 37 avertissements préexistants | signaux faibles noyés et effets React fragiles | budget bloquant 37 livré en v2.570; corriger progressivement jusqu'à zéro sans jamais relever le plafond |
| TD-003 | Moyenne | Documentation | `CLAUDE.md` contenait encore des faits v2.80 (261 outils) alors que le produit est en v2.569 | décisions prises sur une architecture inexistante | guide courant court, `ARCHITECTURE.md` canonique et test automatique de cohérence livrés en v2.569 |
| TD-004 | Moyenne | Validation | le runner historique s'arrêtait au premier échec | résultats non exécutés présentés implicitement comme couverts | fermé en v2.568 : 237/237 étapes exécutées, rapport atomique et mode `--fail-fast` explicite |
| TD-005 | Faible | Gouvernance | version et journal touchent de nombreux commits | bruit de diff et conflits entre agents | conserver un commit atomique par tranche; étudier une note de version générée sans retirer la traçabilité actuelle |
| TD-006 | Moyenne | Persistance | la matrice globale classe encore la persistance `partial` | restauration hors machine non démontrée sur stockage immuable | exercice de restauration sur support distinct, preuve d'intégrité et procédure portable testée |
| TD-007 | Élevée | Sécurité | SEC-006, SEC-008 et SEC-009 sont fermés en v2.582, mais la matrice globale garde la fermeture de dette sécurité `partial` | les entrées restantes pourraient être confondues avec un domaine globalement vérifié | fermer ou faire accepter explicitement chaque entrée du registre sécurité; aucun statut `verified` par défaut |
| TD-008 | Faible | Tests Qdrant | le gate 250/250 réussit mais un `QdrantClient.__del__` signale `sys.meta_path is None` à l'extinction d'un processus | bruit de sortie et fermeture implicite d'un client local dans au moins un test | identifier le propriétaire exact, fermer explicitement le client avant la fin de l'interpréteur et ajouter une assertion d'absence d'avertissement |

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
