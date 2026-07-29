# Certification des outils Marvin

## Périmètre

Version : 2.490.0  
Date : 2026-07-29  
Registre : 344 outils  
Objectif : distinguer les contrats vérifiés, les exécutions réelles sûres et les capacités
conditionnées par un compte, un matériel ou une cible externe.

## Niveaux de preuve

| Niveau | Signification | État v2.490 |
|---|---|---:|
| Registre | Schéma, exécuteur et harness commun présents | 344/344 |
| Domaine isolé | Cas nominaux, erreurs, permissions et rollback testés sans effet externe | Gate global |
| Réel sûr | Exécution sur ce PC, en lecture seule ou sans effet métier | 45/45 |
| Réel conditionnel | Nécessite compte, VM, cible SSH, matériel ou service configuré | À valider selon disponibilité |
| Réel sortant | Envoi, publication, suppression ou mutation distante | Test seulement avec confirmation et cible dédiée |

Un outil n'est jamais déclaré opérationnel uniquement parce qu'il existe dans le registre.
L'interface doit exposer `disponible`, `dégradé` ou `indisponible` lorsque son prérequis manque.

## Résultats réels de la tranche

- `/api/health` : backend disponible, Ollama disponible, 344 outils synchronisés.
- `system_self_test(include_web=true)` : 45 réussites, zéro échec.
- Sondes couvertes : calcul, date, conversion, hash, JSON, système Windows, disques, services,
  utilisateurs, GPU, processus, logiciels, chemins, agenda, comptes e-mail, mémoire, notes,
  tâches, facturation, SSH configuré, ping local, recherche SearXNG, météo et presse-papiers.
- Chat local : sélection de `pc_get_real_paths`, exécution, reçu de preuve et réponse finale.
- Modèles : Kimi K3 sélectionné en premier pour un besoin agentique; refus HTTP 402 observé,
  repli Cloud vers MiniMax M3, aucun repli local en mode Ultra.
- Web : `web_research` sélectionné pour une demande courte; le LLM a librement produit cinq
  requêtes dans le budget SearXNG exclusif, les résultats hors sujet ont été filtrés et la
  documentation officielle Python a été retrouvée en environ 28 secondes.

Les fichiers de preuve générés pendant la validation se trouvent sous `artifacts/` et ne
constituent pas des sources de vérité durables.

## Capacités conditionnelles

Les opérations suivantes ne doivent pas être déclenchées artificiellement sur des données
réelles pour satisfaire un compteur de test :

- envoi d'e-mail, création d'événement distant et publication;
- suppression de fichiers, réglages Windows, registre, services et pare-feu;
- commandes SSH sur une machine non dédiée;
- génération vidéo distante facturable;
- validation Windows/Linux en VM lorsqu'aucune VM saine n'est disponible.

Elles sont couvertes par leurs tests de domaine, permissions, confirmations, idempotence et
rollback. Leur certification réelle exige une cible de test dédiée et doit conserver le reçu
correspondant.

## Commandes reproductibles

```text
# Target: Windows 11
# Shell/CLI: PowerShell 5.1
# Privileges: Utilisateur
# Objective: Exécuter le gate global sans build Next.js
```

```powershell
$env:PYTHONIOENCODING = 'utf-8'
backend\.venv\Scripts\python.exe scripts\check_marvin.py --quick
```

```text
# Target: Marvin local
# Shell/CLI: PowerShell 5.1
# Privileges: Utilisateur
# Objective: Vérifier les services déjà démarrés
```

```powershell
backend\.venv\Scripts\python.exe scripts\check_marvin.py --live
```

## Rollback

Cette tranche ne modifie aucun schéma de base. Le rollback consiste à réverter atomiquement le
commit v2.490, redémarrer uniquement le backend, puis exécuter `check_marvin.py --quick`.
Les observations de fiabilité Model Market sont append-only et peuvent être conservées : elles
décrivent des résultats réellement observés et ne modifient aucun contenu métier.
