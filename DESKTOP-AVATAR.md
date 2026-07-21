# Avatar de bureau Marvin

Cible technique : Windows 11, Next.js 16.2.6, Electron 43.1.1
Niveau requis : N1
Impact de production : Faible
Privilèges requis : Utilisateur standard
Sauvegarde préalable : Aucune donnée métier n'est modifiée
Plan de rollback : supprimer le raccourci et la dépendance Electron optionnelle

## Objectif

L'avatar fournit une fenêtre de conversation toujours visible pour parler à Marvin, saisir
une demande multiligne, relire l'historique complet de la conversation active (le panneau
défile), démarrer une nouvelle conversation ou reprendre l'une des 8 dernières depuis un
historique intégré, suivre la mission Code active, écouter la réponse, ouvrir l'interface
complète, démarrer ou arrêter les services Marvin et fermer uniquement l'avatar. Le mode
conversation (520 x 680 par défaut) peut basculer en mode compact (390 x 470); position et
dimensions sont restaurées au lancement.

L'avatar ne remplace pas l'application : il charge la route locale
`http://127.0.0.1:3000/avatar`. Si Marvin est arrêté, une page locale hors ligne permet de le
démarrer. L'arrêt conserve volontairement Ollama afin de ne pas interrompre un autre usage local.

## Installation et lancement

```text
# Target: Windows 11
# Shell/CLI: PowerShell 5.1 ou 7
# Privileges: Utilisateur standard
# Objective: Créer le raccourci Bureau de l'avatar
```

```powershell
$ProjectRoot = (Get-Location).Path
powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot 'scripts\install-desktop-avatar.ps1')
```

Ces commandes supposent que PowerShell est placé à la racine de Marvin. Lancer ensuite
`Marvin Avatar` depuis le Bureau ou `LANCER-AVATAR-MARVIN.bat` depuis cette racine. Dans
l'interface principale, un clic sur le robot Möbius en haut de la barre latérale lance ou
remet au premier plan la même instance. Tous les chemins du raccourci sont calculés
dynamiquement à partir du dossier d'installation.
Le raccourci global `Ctrl+Maj+Espace` rappelle la fenêtre existante au premier plan sans
créer de seconde instance.

## Sécurité et fonctionnement

- `nodeIntegration` est désactivé, `contextIsolation`, `sandbox` et `webSecurity` sont actifs.
- Le preload n'expose que des opérations IPC nommées et bornées; aucune primitive de commande générique
  n'est accessible au contenu web.
- Les nouvelles fenêtres et les navigations hors de `/avatar` sont refusées.
- Seul le microphone, demandé par l'origine locale de l'avatar, peut être autorisé.
- Les commandes d'arrêt ciblent uniquement les processus écoutant sur 3000 et 8005 dont le
  processus ou un parent appartient à la racine du projet.
- Le profil Electron est stocké sous `%LOCALAPPDATA%\Marvin\DesktopAvatar`.

## Validation

```text
# Target: Windows 11
# Shell/CLI: PowerShell
# Privileges: Utilisateur standard
# Objective: Vérifier le contrat statique, l'interface et l'absence de dépendance vulnérable connue
```

```powershell
npm run check:avatar
npm run check:voice
npm run lint -- --quiet
npm audit
```

Critères de réussite : 30 assertions avatar, 10 assertions vocales, aucune erreur ESLint et
aucune vulnérabilité déclarée par npm audit au moment du test.

## Arrêt et rollback

Fermer uniquement l'avatar avec son bouton de fermeture. Pour retirer l'intégration Bureau :

```powershell
Remove-Item -LiteralPath "$env:USERPROFILE\Desktop\Marvin Avatar.lnk" -Force
```

Cette suppression ne touche ni Marvin, ni les conversations, ni Ollama. La dépendance Electron
peut ensuite être retirée de `devDependencies` avec npm si l'avatar n'est plus souhaité.
