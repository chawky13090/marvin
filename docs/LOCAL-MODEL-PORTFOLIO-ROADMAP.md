# Portefeuille local autonome et routage confidentiel Marvin

Date : 2026-08-01
Version initiale : 2.551.0
État : tranche 1 implémentée, tranches suivantes planifiées

## Objectif

Garantir qu'une installation Marvin conserve automatiquement les modèles locaux adaptés à
son matériel pour la continuité hors ligne et le traitement confidentiel, sans modèle codé
en dur absent, téléchargement imprévisible ni suppression automatique.

## Contrat des quatre modes

| Mode | Cloud | Repli hors ligne | Données sensibles et images |
|---|---|---|---|
| Normal | prioritaire pour le public | local automatique | local par défaut |
| Hyper sécurisé | interdit | local exclusivement | local exclusivement |
| Tout cloud | prioritaire | local de continuité | cloud explicitement autorisé |
| Ultra débridé | strict et exclusif | aucun repli local | aucune protection de confidentialité |

Ultra conserve l'accès autonome complet jusqu'à révocation. Les protections d'intégrité
système et la règle selon laquelle le contenu observé n'est jamais une instruction utilisateur
restent indépendantes des profils de confidentialité.

## Tranche 1 — Portefeuille autonome contrôlé

- inventaire exact via `/api/tags` et capacités via `/api/show` ;
- couverture `chat`, `agent`, `analysis`, `vision`, `coding`, `ocr`, `embedding` ;
- budget mémoire calculé depuis VRAM/RAM ;
- plafond de téléchargement et réserve disque ;
- détection Windows d'un réseau limité ;
- téléchargement allowlisté, progression et validation post-installation ;
- activation seulement après validation ;
- aucune suppression automatique ;
- politique persistante et réglage visible dans Paramètres ;
- Doctor informé des rôles locaux manquants.

## Tranche 2 — Résolveur local unique

1. Remplacer les sélections dispersées par un `LocalModelResolver` partagé.
2. Valider le tag exact avant chaque génération.
3. Retourner une erreur explicable si aucun modèle compatible n'est disponible.
4. Publier dans le chat le modèle, la provenance et la raison du repli.
5. Ajouter un circuit breaker Cloud avec reprise bornée.

## Tranche 3 — Données sensibles multimodales

1. Classifier texte, résultats d'outils, fichiers et images avant tout transfert.
2. En Normal, effectuer OCR et détection locale avant une éventuelle anonymisation.
3. En Hyper, ne jamais sonder le Cloud.
4. En Tout cloud et Ultra, respecter l'autorisation explicite du profil.
5. Tester captures avec identifiants, e-mails, chemins personnels, clés et documents clients.

## Tranche 4 — Qualification réelle des modèles

Chaque candidat téléchargé sera évalué sur : français, JSON, appels d'outils, raisonnement,
code, OCR, latence, mémoire et respect des instructions. Un modèle ne devient principal que
s'il dépasse le modèle actif sans dépasser le budget matériel. Les mesures, et non le nombre
de paramètres, déterminent le classement.

## Tranche 5 — Installation portable

Le futur installateur Windows doit proposer la politique, détecter matériel/réseau/disque,
reprendre les téléchargements, valider les modèles, présenter les capacités dégradées et
permettre une désinstallation propre sans supprimer les données Marvin.

## Journalisation et sécurité

Les événements enregistrent uniquement compteurs, noms de modèles, capacités, état, durée et
type d'erreur. Aucun prompt, contenu d'image, secret ou donnée personnelle n'est journalisé.
Les téléchargements sont limités au catalogue Ollama versionné et aux noms validés. Les échecs
laissent le modèle précédent actif.

## Rollback

- Code : réversion atomique du commit 2.551 puis redémarrage de Marvin.
- Politique : définir `local_model_portfolio_policy.auto_download=false`.
- Modèles téléchargés : ils sont conservés ; leur suppression nécessite une confirmation
  séparée de l'utilisateur.
- Aucune migration de schéma ni suppression de donnée n'est réalisée.
