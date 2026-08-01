# Audit local borné de Marvin — 1er août 2026

## Contexte

L'utilisateur a demandé l'arrêt du scan Codex Security profond parce que son coût avait
consommé environ 20 % de ses crédits et que Bitdefender déclenchait des alertes répétées.
Le scan multi-agent a donc été annulé avant production de son manifeste terminal. Il ne
constitue pas un audit de sécurité achevé et aucun résultat de sécurité ne doit en être déduit.

Identifiants de diagnostic conservés :

- premier scan : `d36ba89e-e53a-49cc-8a1f-147f5a0d7fd1`, interrompu par `spawn EPERM` ;
- second scan : `4a92fae5-3cb2-4561-8d64-5dadcb19e720`, annulé explicitement ;
- artefact du second scan :
  `C:\Users\Chawb\AppData\Local\Temp\codex-security-scans-sOVuzK\secretary-ai\d272bc236195721626fbe35e45f26a37bfa836ac_20260801T200412Z_49xdwtl2`.

Le premier défaut `spawn EPERM` provenait de la résolution Windows de la commande `codex`.
La variable utilisateur `CODEX_CLI_PATH` pointe maintenant vers le binaire Codex CLI local.
Ce réglage appartient au poste de développement et ne doit pas être intégré à l'installeur
Marvin.

## Incident Bitdefender

Les alertes observées correspondaient à des workers de découverte exécutant des recherches
PowerShell et `rg` en parallèle sur des chaînes sensibles telles que `secret`, `token`,
`Invoke-Expression`, `firewall` ou `Remove-Item`. La commande visible dans l'alerte était une
inspection en lecture, pas l'exécution de ces primitives. Le scan a néanmoins été arrêté pour
éviter toute nouvelle alerte et toute consommation supplémentaire.

Ne pas créer d'exclusion globale pour `powershell.exe`, `C:\Windows`, le profil utilisateur ou
le dépôt entier. Ne pas désactiver durablement l'antivirus. Une reprise éventuelle du scan
profond devra se faire dans une VM Windows isolée exécutant elle-même Codex, ou avec une règle
Bitdefender étroite, temporaire et vérifiée selon la documentation officielle.

## État réel des services

- backend FastAPI : HTTP 200 sur `127.0.0.1:8005`, version chargée avant redémarrage `2.559.0` ;
- frontend Next.js : HTTP 200 sur `127.0.0.1:3000` ;
- Ollama : listener sur `127.0.0.1:11434`, état `ollama=true` dans `/api/health` ;
- SearXNG : conteneur `marvin-searxng` actif, port dynamique
  `127.0.0.1:8391 -> 8080`, accueil HTTP 200 et recherche JSON HTTP 200 ;
- ancien port `8890` : non utilisé sur cette instance et ne constitue pas une panne.

## Défauts détectés et corrigés

Trois tests de non-régression avaient conservé des contrats antérieurs aux consolidations :

1. `scripts/test_agent_tool_postprocess.py` attendait encore une critique LLM synchrone avant
   diffusion d'une confirmation. Cette critique a été volontairement retirée en v2.556 pour
   éviter 10 à 30 secondes de latence. Le test vérifie maintenant l'absence de cet appel et la
   conservation de la normalisation et du scan documentaire.
2. `scripts/test_web_runtime.py` cherchait les anciens appels directs
   `supervisor.shutdown()` et `web_runtime.close()` dans `main.py`. Le test vérifie maintenant
   leur ordre réel à travers `shutdown_runtime.run`, sans affaiblir le contrat d'arrêt borné.
3. `scripts/smoke_test_api.py` attendait l'ancienne politique Model Market
   `passive_real_calls_only`. Le moteur et son test unitaire utilisent
   `documented_priors_plus_real_outcomes`; le smoke test est aligné sur ce contrat actuel.

Aucun comportement métier, schéma, secret ou donnée persistante n'a été modifié.

## Validations réellement exécutées

- `npm run check:quick` : **235/235 étapes réussies** ;
- `npm run check:api` : **28/28 contrats API réussis** ;
- `npm run check:pages` : **41/41 pages réussies** ;
- `scripts/test_agent_tool_postprocess.py` : réussi ;
- `scripts/test_web_runtime.py` : réussi ;
- `scripts/check_architecture.py` :
  `Marvin 2.560.0 | 363 outils | 390 routes | 41 pages | harness 363/363 | 81 restrictions` ;
- `scripts/check_runtime.mjs` : Node.js `26.2.0`, ABI 147 et `sharp 0.35.3` chargés ;
- SearXNG `8391` : accueil et recherche JSON HTTP 200.

## Limites

- Le scan sécurité profond n'est pas terminé et ne doit pas être présenté comme réussi.
- Aucun envoi d'e-mail, installation, suppression, action PC destructive ou mission cloud
  payante n'a été exécuté pendant cette tranche.
- Le build Next.js complet n'a pas été rejoué ; `check:quick` l'ignore volontairement. Le lint
  frontend inclus dans la suite a réussi.
- Le backend en cours d'exécution reste en `2.559.0` jusqu'au prochain redémarrage contrôlé ;
  les fichiers sources et métadonnées sont en `2.560.0`.
- Les fichiers non suivis déjà présents dans le dépôt ont été laissés intacts.

## Rollback

Cette tranche ne contient aucune migration. Rollback recommandé : réversion atomique du
commit v2.560 puis redémarrage contrôlé de Marvin. Avant commit, les seuls fichiers de cette
tranche sont les trois tests, les métadonnées de version, `AGENTS.md`, ce rapport et
`DEVELOPMENT-JOURNAL.md`.

## Suite recommandée

1. Réactiver Bitdefender s'il est encore désactivé et vérifier que les alertes cessent.
2. Ne pas relancer le scan profond sur l'hôte sans décision explicite.
3. Au prochain créneau de maintenance, redémarrer Marvin pour charger la version `2.560.0`,
   puis vérifier `/api/health` et une recherche SearXNG réelle.
4. Réserver le build Next.js complet et les tests destructifs/externes à une fenêtre dédiée.
