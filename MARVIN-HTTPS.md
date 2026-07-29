# Marvin HTTPS LAN

## Contrat

La passerelle Caddy 2.11.4 termine TLS sur le port `8443`. Le frontend écoute uniquement sur
`127.0.0.1:3000` et FastAPI uniquement sur `127.0.0.1:8005`. Sous HTTPS,
`/marvin-api/*` est transmis à FastAPI après retrait du préfixe; les autres chemins sont
transmis à Next.js. Les routes `/api` propres à Next.js restent donc intactes.

Le port non standard est volontaire pour la tranche progressive : il évite une élévation
administrateur et les collisions avec les services Windows. L'installateur final pourra
réserver le port `443` après précheck et consentement.

## Installation et démarrage

```text
# Target: Windows 11 x64
# Shell/CLI: Windows PowerShell 5.1
# Privileges: Utilisateur
# Objective: Installer le binaire Caddy épinglé, vérifier SHA-512 et générer la configuration
```

```powershell
.\scripts\install-marvin-https.ps1 -Port 8443
```

`start.bat` démarre ensuite automatiquement la passerelle si elle est installée.

## Approbation de l'autorité

L'autorité est propre à chaque installation Marvin. Vérifier son empreinte SHA-256 sur le PC
principal avant de l'approuver sur un second appareil. Ne jamais approuver une autorité reçue
sans vérification indépendante de cette empreinte.

```text
# Target: Windows 11 x64, appareil jumelé
# Shell/CLI: Windows PowerShell 5.1
# Privileges: Utilisateur
# Objective: Approuver l'autorité Marvin pour l'utilisateur courant
```

```powershell
.\scripts\trust-marvin-https.ps1 -Scope CurrentUser
```

Le certificat public peut être téléchargé depuis Paramètres > Connexions par une session déjà
jumelée. La clé privée de l'autorité ne quitte jamais `runtime/https/data`.

## Journalisation et sécurité

La passerelle ne conserve pas de journal d'accès afin de ne pas dupliquer URLs, paramètres,
adresses et métadonnées sensibles. Les décisions d'accès restent dans les journaux structurés
et expurgés du backend. Les erreurs Caddy sont visibles dans sa console de runtime; leur
intégration ultérieure à la rotation structurée devra exclure requêtes, cookies et en-têtes.

Les en-têtes HSTS, `nosniff`, `Referrer-Policy` et `Permissions-Policy` sont posés à la
passerelle. Le code de jumelage est valable cinq minutes, devient invalide après une réussite
et le profil par défaut est `standard`.

## Rollback

```text
# Target: Windows 11 x64
# Shell/CLI: Windows PowerShell 5.1
# Privileges: Utilisateur
# Objective: Arrêter la passerelle et retirer son runtime local
```

```powershell
.\scripts\rollback-marvin-https.ps1 -Confirm:$false
```

HTTP sur `3000/8005` reste disponible uniquement depuis le PC principal. Le rollback ne
modifie aucune base, session ou donnée métier. Retirer ensuite manuellement l'autorité `Caddy Local
Authority - 2026 ECC Root` du magasin utilisateur si la confiance doit aussi être révoquée.

## Limites connues

- L'approbation de l'autorité sur Android, iOS, macOS et Linux demande encore un parcours
  spécifique à la plateforme.
- Le port standard `443`, le service Windows et la révocation automatisée appartiennent à la
  tranche installateur suivante.
