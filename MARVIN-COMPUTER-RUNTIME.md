# Marvin Computer Runtime

## Objectif

Le Computer Runtime fournit au Runner agentique une façade unique pour observer et piloter
le navigateur ou le bureau Windows. Il applique une boucle courte : observer, agir, observer
de nouveau, vérifier l’effet demandé, puis signaler `needs_repair=true` si la preuve manque.
Le LLM choisit l’action. Le runtime ne choisit pas l’objectif métier et ne contourne jamais
le gateway d’outils.

## Architecture

| Composant | Responsabilité |
|---|---|
| `backend/computer_runtime.py` | Contrat unifié Observe/Act/Verify |
| `backend/web_browser.py` | Session Playwright persistante et locators sémantiques |
| `backend/tool_domains/pc_control.py` | Fenêtres et contrôles Windows UI Automation |
| `backend/tool_gateway.py` | Autorisation, preuve, idempotence et audit |
| `backend/policy_engine.py` | Classement de l’effet et décision d’autorisation |
| `backend/capability_discovery.py` | Description et découverte par le LLM |

Les actions de lecture sont `observe`, `verify`, `screenshot`, `list_windows` et `wait`.
Les actions ayant un effet sont `open`, `focus`, `click`, `double_click`, `right_click`,
`move`, `drag`, `type`, `keypress`, `scroll`, `navigate` et `commit`.

Une observation peut associer :

- un arbre UIA ou DOM pour le ciblage sémantique ;
- des `element_ref` opaques, valides cinq minutes et impossibles à inventer ;
- une capture transmise au modèle comme entrée multimodale ;
- un `frame_id` liant les coordonnées de la capture aux coordonnées réelles de l'écran.

Le modèle choisit la stratégie et peut basculer entre sémantique et vision après un échec.
Le runtime borne la durée et les répétitions, mais ne choisit ni l'application, ni le
parcours, ni l'objectif à la place du modèle.

## Modèle d’autorisation

- Mode Normal : une action sensible produit une demande Oui/Non dans le chat.
- Mode Auto : autorisation temporaire bornée par sa politique.
- Accès complet : reste actif jusqu’à révocation explicite, y compris après redémarrage.
- Les contrôles de schéma, de portée, de risque, d’idempotence et d’audit restent actifs.
- `commit` est obligatoire pour le clic final d'une réservation, d'un achat, d'une
  publication ou d'un envoi et demande toujours un clic Oui/Non dans le chat, même en
  Accès complet.
- Une preuve d’exécution dérivée de l’accès complet expire après 60 secondes. La persistance
  du choix utilisateur ne crée donc pas de jeton d’exécution rejouable.
- Les fenêtres élevées restent inaccessibles à un Marvin non élevé. Le runtime ne contourne
  ni UAC, ni authentification, ni CAPTCHA.

## Limites connues

- La session Playwright est isolée du profil Chrome personnel. Elle ne possède pas
  automatiquement les sessions déjà connectées de l’utilisateur.
- UI Automation dépend de la qualité de l’arbre exposé par l’application. Le Bloc-notes
  Windows 11 expose son éditeur comme un `Document` anonyme et ne restitue pas toujours son
  contenu ; l’action peut réussir alors qu’une preuve textuelle demandée reste négative.
- Les applications sans sémantique UIA utilisent le repli visuel borné. Sa qualité dépend
  de la capacité vision du modèle actif ; un modèle texte conserve le parcours sémantique.
- Une capture peut contenir des données privées. Elle suit strictement le profil de
  confidentialité : les outils inconnus ou privés provoquent le repli local sauf en Ultra
  débridé, où l'utilisateur a explicitement accepté le traitement Cloud.

## Validation

```text
# Target: Windows 11
# Shell/CLI: PowerShell 5.1 ou 7
# Privileges: Utilisateur
# Objective: Valider les contrats déterministes

backend\.venv\Scripts\python.exe scripts\test_computer_runtime.py
backend\.venv\Scripts\python.exe scripts\test_tool_domain_pc_control.py
backend\.venv\Scripts\python.exe scripts\test_tool_approval_flow.py
backend\.venv\Scripts\python.exe scripts\check_architecture.py
```

Un test navigateur réel doit naviguer vers une page publique, cliquer un élément par rôle et
nom, puis vérifier l’URL ou le texte obtenu. Un test Windows réel doit au minimum lister les
fenêtres et lire les contrôles d’une application non élevée.

## Journalisation, données et rollback

Le gateway journalise la capacité, l’effet, la décision, la corrélation et le résultat. Les
textes saisis et résumés d'engagement sont remplacés par leur longueur dans les logs. Les
captures ne sont pas ajoutées au contexte texte ni aux arguments journalisés ; elles sont
transmises au modèle selon le profil de confidentialité. Aucun nouveau secret ni schéma
n’est créé.

Le rollback est la réversion atomique du commit de la version 2.510, suivie du redémarrage du
backend et du frontend. Les réglages historiques restent lisibles.
