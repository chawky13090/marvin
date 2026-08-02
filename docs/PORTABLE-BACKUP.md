# Sauvegarde portable Marvin

## Contexte et choix

Le format local `marvin_full_*.mrvfull` reste le meilleur choix pour une restauration rapide
sur la même identité Windows : sa clé aléatoire AES-256-GCM est protégée par DPAPI
`CurrentUser`. Il n'est volontairement pas portable.

Le format `.mrvportable` répond au transfert vers un autre PC. Sa clé AES-256-GCM est dérivée
d'une phrase secrète par scrypt (`N=2^17`, `r=8`, `p=1`, sel aléatoire de 16 octets). L'en-tête
est authentifié et chaque fichier interne est contrôlé par SHA-256. Les paramètres suivent le
minimum scrypt publié par l'[OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html),
et l'usage du nonce 96 bits, du tag complet et des données associées suit la
[documentation AES-GCM de cryptography](https://cryptography.io/en/latest/hazmat/primitives/symmetric-encryption/).

Les fichiers `windows_secrets.dpapi.json` et `windows_secrets.metadata.json` sont exclus. Après
transfert, il faut reconnecter OAuth, e-mails, SSH et tout autre identifiant local. La phrase
secrète n'est ni argument de commande, ni variable d'environnement, ni journal : elle est
demandée avec une saisie masquée.

## Création

```text
# Target: Windows 11, Marvin 2.584+
# Shell/CLI: PowerShell 5.1 ou 7
# Privileges: utilisateur propriétaire de Marvin
# Objective: créer un nouveau bundle portable chiffré sur un support choisi
```

```powershell
Set-Location -LiteralPath 'C:\Users\Chawb\secretary-ai'
& '.\backend\.venv\Scripts\python.exe' '.\scripts\create-portable-backup.py' 'E:\Marvin\marvin-export.mrvportable'
```

Le fichier de destination ne doit pas exister. Saisir puis confirmer une phrase secrète d'au
moins 12 caractères. Pour une sauvegarde réelle, utiliser une phrase longue et unique conservée
hors du PC ; sa perte rend le bundle irrécupérable.

## Vérification et restauration isolée

La commande suivante n'écrase jamais `data`. Elle extrait vers un dossier vide ou absent afin
de permettre une inspection, un contrôle antivirus et une migration supervisée.

```text
# Target: Windows 11, Marvin 2.584+
# Shell/CLI: PowerShell 5.1 ou 7
# Privileges: utilisateur standard
# Objective: authentifier et extraire le bundle vers une zone isolée
```

```powershell
Set-Location -LiteralPath 'C:\Users\Chawb\secretary-ai'
& '.\backend\.venv\Scripts\python.exe' '.\scripts\restore-portable-backup.py' 'E:\Marvin\marvin-export.mrvportable' 'C:\Temp\Marvin-Restore-Verify'
```

Critères de réussite : `success=true`, `integrity_verified=true`, `portable=true` et
`reauthentication_required=true`. Une phrase incorrecte, un octet modifié, un manifeste
incohérent ou une destination non vide échoue sans produire de restauration partielle.

## Rollback et limites

Cette tranche ne modifie aucune donnée existante et ne remplace aucun format historique. Le
rollback applicatif est la réversion atomique du commit v2.584. Un bundle `.mrvportable` déjà
créé reste autonome. La suppression du bundle est une opération utilisateur distincte.

La restauration automatique sur `data` n'est pas encore autorisée : elle nécessitera arrêt
confirmé de Marvin, sauvegarde locale préalable, application transactionnelle, réconciliation
des projections et compensation. SEC-024 et TD-006 restent donc ouverts jusqu'à un exercice
réel sur un second support et un second poste.
