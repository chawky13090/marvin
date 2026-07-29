# Accès LAN protégé de Marvin

Date de référence : 2026-07-29
Version : 2.466.0

## Frontière de confiance

La boucle locale (`127.0.0.1` et `::1`) représente le compte Windows qui exécute Marvin.
Toute autre adresse doit présenter une session jumelée. Le backend peut donc rester joignable
par le téléphone ou un autre PC sans rendre les 344 outils anonymement accessibles.
La boucle locale reçoit automatiquement une session signée au premier contrôle : le proxy
Next.js peut ainsi protéger uniformément ses propres routes serveur sans stockage JavaScript.

Le jumelage utilise un code temporaire de forte entropie, renouvelé au redémarrage et visible
uniquement dans **Paramètres > Connexions** depuis le PC principal. Cinq échecs sur dix
minutes bloquent les tentatives du client. Le code n'est jamais écrit dans un log.

## Session

- jeton signé HMAC-SHA-256, versionné et lié au client ;
- clé aléatoire de 256 bits conservée dans le coffre DPAPI utilisateur ;
- expiration absolue de douze heures ;
- cookie de session non persistant, `HttpOnly`, `SameSite=Lax` ;
- cookie CSRF distinct, `SameSite=Strict`, comparé en temps constant au header
  `X-Marvin-CSRF` ;
- contrôle strict de l'origine pour toute mutation navigateur ;
- logout supprimant les deux cookies ;
- refus WebSocket avec le code 4401 et HTTP avec 401/403 expurgés.

## Autorisation par capacité

Le jumelage attribue un profil signé et non modifiable côté navigateur :

- `read_only` : lectures sans administration ;
- `standard` : lectures et opérations métier courantes ;
- `full` : ajoute administration, outils, fichiers, stockage, SSH, VM, Code Workspace,
  sauvegardes, identifiants, OAuth et réglages.

Le profil complet reste sélectionné par défaut afin de préserver le comportement existant.
Le propriétaire peut choisir un profil plus faible lors du jumelage d'un téléphone ou d'un
autre PC. La décision est recalculée sur chaque requête par la garde FastAPI. Le proxy Next
transmet uniquement chemin et méthode à l'introspection; il ne décide jamais lui-même.
OpenAPI publie `x-marvin-capability` sur chaque opération protégée.

`SameSite=Lax` est retenu pour conserver les retours OAuth en navigation principale.
Il ne remplace pas la défense CSRF : toutes les mutations navigateur exigent aussi origine
valide et double-submit. Les clients CLI locaux sans en-têtes navigateur restent utilisables.

## Interface et flux

`LanAccessGate` vérifie la session avant de monter le reste de l'interface. Sur un appareil
non jumelé, aucune page, conversation ou worker client n'est rendu. Le pont de
`lib/backend.js` conserve le cookie HttpOnly hors JavaScript, active `credentials=include`
et ajoute uniquement le jeton CSRF aux mutations FastAPI. Les flux EventSource distants
utilisent `withCredentials`; WebSocket reçoit automatiquement le cookie du navigateur.
Le `proxy.js` Next.js 16 valide chaque appel `/api/*` auprès de l'introspection FastAPI et
échoue fermé. Seule `/api/status`, sonde de démarrage historique sans mutation, reste
publique. Les anciens en-têtes CORS génériques de Next sont supprimés. Turbopack autorise
exactement les IPv4 détectées sur la machine au démarrage, ce qui évite tout chemin statique
ou adresse LAN codée en dur lors d'une installation sur un autre PC.

## Limites restantes

Le trafic LAN utilise encore HTTP. La session est liée au client et courte, mais un attaquant
capable d'intercepter le réseau peut observer les données métier. Le statut SEC-001 reste
donc `MITIGATED`. La fermeture exige HTTPS local avec installation/rotation de certificat,
activation LAN explicite et autorisation serveur par capacité. Le middleware ne remplace pas
les confirmations d'actions ni les 78 restrictions du harness.

## Logs

`lan_pair` conserve uniquement succès et classe d'erreur; `lan_logout` uniquement le succès.
Adresse IP, code, cookie, CSRF, signature et contenu métier sont interdits. Les refus 401/403
passent dans les métriques HTTP agrégées existantes sans corps de requête.

## Rollback

Réversion atomique des commits v2.466 puis v2.465. La clé DPAPI inutilisée peut rester sans impact; sa
suppression éventuelle doit être une opération explicite après retour confirmé. Aucun schéma
SQLite ni contenu métier n'est modifié.
