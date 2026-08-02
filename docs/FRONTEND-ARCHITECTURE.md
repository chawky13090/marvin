# Architecture frontend et stratégie de consolidation

État de départ vérifié en v2.570. Le frontend Next.js 16.2.12 utilise App Router, React 19,
JSX et Turbopack. La consolidation doit préserver les 41 pages, les flux SSE reprenables, le
mode vocal, les confirmations, l'état des conversations et l'accès aux 363 outils.

## Frontières cibles

| Couche | Responsabilité | Interdit |
|---|---|---|
| `app/**/page.*` | composition de page, paramètres de route et état propre au parcours | catalogue métier massif, client HTTP dupliqué, composants génériques |
| `components/<domain>/` | composants visuels cohésifs d'un domaine | persistance directe, URL backend codée en dur |
| `lib/hooks/` | état et effets réutilisables avec nettoyage explicite | rendu JSX et règles d'autorisation serveur |
| `lib/` | transports, normalisation et fonctions pures | état React global implicite |
| `components/ui/` | primitives accessibles et sans logique métier | appels réseau |

## Baseline et budget

`config/frontend-baseline.json` recense les six exceptions historiques au plafond de 1 200
lignes. `scripts/check_frontend_baseline.mjs` échoue si une exception grossit, si un nouveau
fichier franchit ce plafond, si ESLint produit une erreur ou si les 37 avertissements actuels
augmentent. Une extraction réussie abaisse le plafond correspondant; le budget ne remonte
jamais pour faire passer un changement.

## Ordre d'extraction

1. `app/outils/page.jsx` : séparer le catalogue statique, les adaptateurs de schéma, les
   composants de sélection de fichier et enfin l'orchestration de page.
2. `components/chat/MessageBubble.jsx` : isoler les cartes de sources, les preuves d'outils et
   les contrôles de lecture sans modifier l'ordre des événements.
3. `app/video/page.jsx`, puis `app/settings/page.jsx` : séparer données, formulaires et vues.
4. `app/devis/page.jsx` et `app/emails/page.jsx` : extraire les sous-domaines avec leurs tests
   de parcours et leurs états d'erreur.

Chaque étape commence par un test de caractérisation, déplace une seule responsabilité,
exécute baseline, lint, build et smoke ciblé, puis possède un commit de rollback autonome.

## Sécurité, observabilité et accessibilité

- Le navigateur ne prend aucune décision d'autorisation : le backend reste l'autorité.
- Aucune donnée sensible n'entre dans les logs frontend ou les artefacts de test.
- Toute requête annulable possède un `AbortController` ou un nettoyage équivalent lorsque le
  cycle de vie le nécessite; les streams conservent leurs curseurs de reprise.
- Les contrôles interactifs utilisent des éléments natifs, des noms accessibles et un focus
  visible. Les états chargement, vide, échec, attente d'autorisation et reprise sont explicites.
- Une optimisation visuelle ne peut ni masquer une erreur d'outil ni transformer une action
  en succès avant sa preuve métier.
