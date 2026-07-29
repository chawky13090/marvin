# Marvin — système UX de référence

## Décision

Marvin utilise une interface de travail calme, dense mais lisible. La suite de Fibonacci
(`3, 5, 8, 13, 21, 34, 55, 89`) définit le rythme des espacements et des rayons. Le nombre
d'or (`61,8 / 38,2`) guide seulement les rapports entre zone principale et panneaux
secondaires. Il ne remplace jamais les contraintes de contenu, d'écran ou d'accessibilité.

## Comparaison des approches

### Nombre d'or strict

Cette approche donne une composition visuellement régulière, mais produit des panneaux
surdimensionnés ou trop étroits selon le viewport et le contenu. Elle est donc rejetée comme
règle absolue.

### Système adaptatif retenu

Les espacements utilisent des jetons Fibonacci. Les largeurs structurantes utilisent
`clamp()` et se rapprochent du rapport d'or sur les grands écrans. Sous 1024 px, les panneaux
secondaires deviennent des tiroirs. Cette solution préserve la lisibilité, les cibles
tactiles et les 344 outils.

Le rail d'outils constitue une exception d'accessibilité volontaire à l'échelle stricte :
72 px en mode compact permettent de centrer une cible de 44 px sans écraser les icônes. Son
état déployé mesure 258 px afin de préserver les intitulés. L'accessibilité et la lisibilité
priment sur la conformité mathématique décorative.

Les outils utilisent des SVG Lucide locaux de 22 px dans une cellule de 48 × 44 px. Le SVG
hérite de `currentColor`, chaque lien couvre toute la largeur et l'état courant est exposé par
`aria-current="page"`. Les groupes de projets suivent le pattern WAI-ARIA disclosure avec un
bouton portant `aria-expanded` et `aria-controls`; un treeview complexe n'est pas utilisé.

## Principes

1. **Contrôle humain visible** : état, progression, annulation, reprise et résultat doivent
   rester dans le contexte de la demande.
2. **Dévoilement progressif** : le chat et l'action principale dominent; outils avancés,
   preuve brute et réglages restent accessibles sans saturer le premier niveau.
3. **Un état, un signal** : aucune animation décorative ne doit concurrencer une progression
   réelle. Le réglage système de réduction des animations est respecté globalement.
4. **Lisibilité vérifiable** : focus clavier explicite, texte secondaire distinct et texte
   atténué suffisamment visible; les libellés ne reposent pas uniquement sur une icône.
5. **Local-first** : aucune police ni ressource visuelle indispensable n'est téléchargée
   depuis un tiers au démarrage.
6. **Réversibilité** : une action IA modifiant un état doit afficher confirmation, preuve ou
   moyen de revenir en arrière selon son risque.

Ces principes croisent les recommandations officielles suivantes :

- WCAG 2.2 : focus visible et non masqué, cibles et interactions clavier;
- Apple Human Interface Guidelines, Generative AI : garder l'utilisateur aux commandes,
  rendre l'IA identifiable, permettre de réessayer ou revenir en arrière et afficher le
  travail en arrière-plan;
- Anthropic, *Building trustworthy agents* : contrôle humain, transparence et confidentialité;
- OpenAI, approche de sûreté : guider, contrôler et auditer les actions;
- Material Design 3 : mise en page canonique adaptative, avec zone principale dominante et
  panneau secondaire lorsque le contexte le justifie.

## Hiérarchie cible

- Niveau 1 : conversation, demande active, progression et réponse.
- Niveau 2 : conversations, projets, modes de travail et livrables.
- Niveau 3 : catalogue complet des outils, réglages, preuves et diagnostics.
- La palette de commandes fournit un accès transversal au clavier sans dupliquer les écrans.

## Accessibilité et sécurité

- WCAG 2.2 AA est la cible minimale; le focus ne doit jamais être masqué.
- Les cibles tactiles restent au moins à 40 px sur interface tactile.
- Les données sensibles ne sont pas ajoutées aux métriques UX. Cette tranche n'ajoute aucun
  tracking, cookie, stockage ni journal.
- Les polices système évitent une fuite de métadonnées vers un fournisseur externe.

## Validation

```text
# Target: Windows 11, Node.js 26
# Shell/CLI: PowerShell
# Privileges: Utilisateur
# Objective: Valider les invariants UX puis compiler avec Turbopack

npm run check:ux
npm run build
```

Une validation visuelle doit couvrir le chat, Code Workspace, les réglages, le clavier, le
viewport mobile et `prefers-reduced-motion`.

## Sources primaires

- https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/
- https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html
- https://developer.apple.com/design/human-interface-guidelines/generative-ai
- https://developer.apple.com/design/human-interface-guidelines
- https://www.anthropic.com/research/trustworthy-agents
- https://openai.com/safety/how-we-think-about-safety-alignment/
- https://m3.material.io/foundations/layout/canonical-examples/overview
- https://design.google/library/control-and-simplicity

## Rollback

Cette tranche ne modifie ni schéma ni donnée persistante. Le retour arrière est la réversion
atomique de son commit Git. Après réversion, exécuter `npm run build`, puis relancer Marvin et
vérifier `/`, `/code` et `/settings`.
