# Registre de dette technique de Marvin

État vérifié le 2026-08-10 pour Marvin 2.605.0. Ce registre interdit de présenter le projet
comme « sans dette » lorsque les preuves ne le permettent pas. Une ligne n'est fermée
qu'après correction, test de non-régression et preuve dans `DEVELOPMENT-JOURNAL.md`.

| ID | Sévérité | Domaine | Preuve actuelle | Risque | Traitement et critère de fermeture |
|---|---|---|---|---|---|
| TD-001 | Fermée | Frontend | zéro fichier JavaScript/JSX au-dessus de 1 200 lignes en v2.578; `app/emails/page.jsx` est passé de 1 321 à 1 181 lignes après les cinq extractions précédentes | risque historique de revue difficile et collisions Claude/Codex | fermé par caractérisations préalables, baseline 121 sources sans exception, builds et gates exhaustifs; toute réintroduction est bloquée |
| TD-002 | Moyenne | Qualité frontend | ESLint passe avec 37 avertissements préexistants | signaux faibles noyés et effets React fragiles | budget bloquant 37 livré en v2.570; corriger progressivement jusqu'à zéro sans jamais relever le plafond |
| TD-003 | Moyenne | Documentation | `CLAUDE.md` contenait encore des faits v2.80 (261 outils) alors que le produit est en v2.569 | décisions prises sur une architecture inexistante | guide courant court, `ARCHITECTURE.md` canonique et test automatique de cohérence livrés en v2.569 |
| TD-004 | Moyenne | Validation | le runner historique s'arrêtait au premier échec | résultats non exécutés présentés implicitement comme couverts | fermé en v2.568 : 237/237 étapes exécutées, rapport atomique et mode `--fail-fast` explicite |
| TD-005 | Faible | Gouvernance | version et journal touchent de nombreux commits | bruit de diff et conflits entre agents | conserver un commit atomique par tranche; étudier une note de version générée sans retirer la traçabilité actuelle |
| TD-006 | Moyenne | Persistance | v2.584 crée et restaure isolément un export portable réel de 1 733 fichiers/618 281 759 octets, sans secrets DPAPI; aucun second support physique n'est actuellement connecté | restauration appliquée hors machine et résilience à la perte du volume C: non encore démontrées | copier sur support distinct/immuable, restaurer sur un second Windows, réauthentifier les secrets puis conserver la preuve d'intégrité |
| TD-007 | Élevée | Sécurité | SEC-006, SEC-008, SEC-009, SEC-011 et SEC-012 sont fermés en v2.583, mais la matrice globale garde la fermeture de dette sécurité `partial` | les entrées restantes pourraient être confondues avec un domaine globalement vérifié | fermer ou faire accepter explicitement chaque entrée du registre sécurité; aucun statut `verified` par défaut |
| TD-008 | Fermée v2.585 | Tests Qdrant | le client global n'était pas rattaché au lifecycle FastAPI et pouvait atteindre `QdrantClient.__del__` après la fermeture de l'interpréteur | fermeture explicite supervisée après les consommateurs, idempotence testée et étape obligatoire du gate |
| TD-009 | Moyenne | Calibration LLM | v2.594 qualifie Granite 4.1 3B par 3/3 cycles d'outil et certifie deux profils liés au matériel : 8K/f16 à 75,5 % de résidence GPU et 32K/q8_0 à 59,89 %. Le produit choisit 8K pour la performance interactive sur GTX 1650 4 Go; la capacité Cloud reste sans override client | confondre le profil produit optimal, le candidat Forge fonctionnel et la capacité Cloud déclarée produirait une baseline non représentative | exécuter le holdout local et la co-résidence sous verrou 32K explicite, puis la sonde Cloud longue sans `num_ctx` et la campagne Forge gelée; conserver les métriques locales et Cloud séparées avant fermeture |
| TD-010 | Moyenne | Routage agentique Windows | l'E2E reste à 90 % en développement et 100 % en holdout avec zéro faux succès. Les anciens 55 %/40,83 % mesuraient l'adoption de `windows_task`. Le rectificatif de noms compatibles donne 73,75 %/51,67 %, mais 132/360 choix ont une action non observable, 13 une condition non observable et 16 noms sont inexistants, dont 15 liés à la recherche de fichiers. Le holdout reste faible sur découverte 25 %, mutation 22,22 %, arrêt de processus, logiciels et services 33,33 % | une moyenne globale masque des familles faibles; les artefacts historiques ne prouvent ni arguments, ni action, ni résultat du premier appel, et deux empreintes runtime ne sont pas récupérables depuis le commit de référence | conserver l'acceptation E2E bornée; instrumenter le prochain corpus pour enregistrer outil+action+arguments validés et résultat, utiliser un nouveau holdout avant toute optimisation produit, imposer un seuil par famille, obtenir 300 exécutions sans faux succès et réduire la médiane d'étapes sans réduire le catalogue ni la liberté du LLM |

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
