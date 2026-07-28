"""Stockage et résolution des identités e-mail, mot de passe ou OAuth2.

Le marqueur OAuth n'est jamais persisté : il est construit à la demande pour les
adaptateurs IMAP/SMTP après rafraîchissement du jeton.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

import database as db
import email_account_vault as vault

OAUTH_PASSWORD_PREFIX = "__MARVIN_OAUTH2__:"
_LOCK = threading.RLock()


def _audit_migration(action: str, count: int) -> None:
    try:
        import audit
        audit.log_action(
            action,
            result={"success": True, "accounts": int(count)},
            source="runtime",
        )
    except Exception:
        pass


def _coerce(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return None
    return value


def _list_persisted() -> list[dict]:
    accounts = _coerce(db.get_setting("email_accounts"))
    if not isinstance(accounts, list):
        accounts = []
    if not accounts:
        legacy = _coerce(db.get_setting("email_config"))
        if isinstance(legacy, dict) and legacy.get("imap_host"):
            accounts = [legacy]
            _persist(accounts)
    return [dict(account) for account in accounts
            if isinstance(account, dict) and account.get("username")]


def _persist(accounts: list[dict]) -> None:
    db.set_setting("email_accounts", accounts)


def _resolved(account: dict) -> dict:
    secret_ref = account.get("_secret_ref")
    if not secret_ref:
        return dict(account)
    secrets = vault.load(str(secret_ref))
    if not secrets:
        raise vault.EmailAccountVaultError(
            "Secrets e-mail absents du coffre DPAPI."
        )
    return {**account, **secrets}


def migrate_legacy_secrets() -> int:
    """Protège puis relit chaque secret avant de nettoyer SQLite."""
    with _LOCK:
        accounts = _list_persisted()
        legacy = _coerce(db.get_setting("email_config"))
        changed = 0
        migrated: list[dict] = []
        created_refs: list[str] = []
        try:
            for account in accounts:
                if vault.extract(account):
                    secret_ref = vault.store(account)
                    created_refs.append(secret_ref)
                    migrated.append(vault.sanitized(account, secret_ref))
                    changed += 1
                else:
                    migrated.append(dict(account))
            if changed:
                _persist(migrated)
                persisted = _list_persisted()
                if any(vault.extract(account) for account in persisted):
                    raise vault.EmailAccountVaultError(
                        "Le nettoyage SQLite des secrets e-mail a échoué."
                    )
            if isinstance(legacy, dict) and vault.extract(legacy):
                legacy_ref = vault.reference(str(legacy.get("username") or ""))
                active_refs = {
                    str(account.get("_secret_ref"))
                    for account in migrated
                    if account.get("_secret_ref")
                }
                if legacy_ref not in active_refs:
                    legacy_ref = vault.store(legacy)
                    created_refs.append(legacy_ref)
                elif not vault.load(legacy_ref):
                    raise vault.EmailAccountVaultError(
                        "Le secret du compte historique est absent."
                    )
                db.set_setting(
                    "email_config",
                    vault.sanitized(legacy, legacy_ref),
                )
                cleaned_legacy = _coerce(db.get_setting("email_config"))
                if not isinstance(cleaned_legacy, dict) or vault.extract(cleaned_legacy):
                    raise vault.EmailAccountVaultError(
                        "Le nettoyage du compte e-mail historique a échoué."
                    )
                changed += 1
            if changed:
                _audit_migration("email_account_secrets_migrated", changed)
            return changed
        except BaseException:
            # Le texte historique reste la source de reprise si SQLite n'a pas été nettoyé.
            if any(vault.extract(account) for account in _list_persisted()):
                for secret_ref in created_refs:
                    vault.delete(secret_ref)
            raise


def list_raw() -> list[dict]:
    migrate_legacy_secrets()
    return [_resolved(account) for account in _list_persisted()]


def save(accounts: list[dict]) -> None:
    with _LOCK:
        persisted: list[dict] = []
        previous: dict[str, tuple[str, dict[str, str]]] = {}
        written: list[tuple[str, str]] = []
        try:
            for account in accounts:
                username = str(account.get("username") or "")
                secret_ref = str(
                    account.get("_secret_ref") or vault.reference(username)
                )
                if secret_ref not in previous:
                    previous[secret_ref] = (username, vault.load(secret_ref))
                secret_ref = vault.store(account)
                written.append((secret_ref, username))
                persisted.append(vault.sanitized(account, secret_ref))
            _persist(persisted)
        except BaseException:
            for secret_ref, username in reversed(written):
                old = previous[secret_ref][1]
                if old:
                    vault.store({"username": username, **old})
                else:
                    vault.delete(secret_ref)
            raise


def upsert(config: dict) -> list[dict]:
    with _LOCK:
        accounts = list_raw()
        username = (config.get("username") or "").strip()
        index = next((i for i, account in enumerate(accounts)
                      if (account.get("username") or "").lower() == username.lower()), None)
        if index is None:
            accounts.append(dict(config))
        else:
            merged = {**accounts[index], **config}
            if not config.get("password") and accounts[index].get("password") and config.get("auth_type") != "oauth2":
                merged["password"] = accounts[index]["password"]
            if config.get("auth_type") == "oauth2" and not config.get("refresh_token") and accounts[index].get("refresh_token"):
                merged["refresh_token"] = accounts[index]["refresh_token"]
            accounts[index] = merged
        save(accounts)
        return accounts


def remove(username: str) -> int:
    with _LOCK:
        persisted = _list_persisted()
        legacy_before = _coerce(db.get_setting("email_config"))
        removed = [account for account in persisted
                   if (account.get("username") or "").lower() == username.lower()]
        remaining = [account for account in list_raw()
                     if (account.get("username") or "").lower() != username.lower()]
        if remaining:
            save(remaining)
        else:
            _persist([])
        removed_refs = {
            str(account["_secret_ref"])
            for account in removed if account.get("_secret_ref")
        }
        if (
            isinstance(legacy_before, dict)
            and str(legacy_before.get("_secret_ref") or "") in removed_refs
        ):
            db.set_setting("email_config", {})
        try:
            for account in removed:
                if account.get("_secret_ref"):
                    vault.delete(str(account["_secret_ref"]))
        except BaseException:
            _persist(persisted)
            if isinstance(legacy_before, dict):
                db.set_setting("email_config", legacy_before)
            raise
        return len(removed)


def rollback_secrets_to_sqlite(*, confirmed: bool) -> int:
    """Rollback explicite avant retour à une version antérieure de Marvin."""
    if confirmed is not True:
        raise ValueError("Confirmation explicite requise.")
    with _LOCK:
        persisted = _list_persisted()
        resolved = [_resolved(account) for account in persisted]
        _persist([
            {key: value for key, value in account.items()
             if key not in {"_secret_ref", "_secret_version"}}
            for account in resolved
        ])
        reread = _list_persisted()
        if len(reread) != len(resolved) or any(
            not vault.extract(account) for account in reread
        ):
            raise vault.EmailAccountVaultError(
                "Le rollback SQLite des secrets e-mail a échoué."
            )
        legacy = _coerce(db.get_setting("email_config"))
        legacy_ref = None
        if isinstance(legacy, dict) and legacy.get("_secret_ref"):
            legacy_ref = str(legacy["_secret_ref"])
            legacy_resolved = _resolved(legacy)
            db.set_setting(
                "email_config",
                {
                    key: value for key, value in legacy_resolved.items()
                    if key not in {"_secret_ref", "_secret_version"}
                },
            )
        refs = {
            str(account["_secret_ref"])
            for account in persisted if account.get("_secret_ref")
        }
        if legacy_ref:
            refs.add(legacy_ref)
        for secret_ref in refs:
            vault.delete(secret_ref)
        _audit_migration("email_account_secrets_rollback", len(resolved))
        return len(resolved)


def _refresh_google(config: dict) -> dict:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token = config.get("access_token")
    refresh_token = config.get("refresh_token")
    expiry = None
    if config.get("token_expiry"):
        try:
            expiry = datetime.fromisoformat(str(config["token_expiry"]).replace("Z", "+00:00"))
            if expiry.tzinfo:
                expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            expiry = None
    credentials = Credentials(
        token=token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.get("oauth_client_id"),
        client_secret=config.get("oauth_client_secret"),
        scopes=config.get("oauth_scopes") or ["https://mail.google.com/"],
        expiry=expiry,
    )
    if not credentials.valid:
        if not credentials.refresh_token:
            raise ValueError("Autorisation OAuth Gmail expirée : reconnecte cette boîte.")
        credentials.refresh(Request())
        config = {**config, "access_token": credentials.token}
        if credentials.expiry:
            config["token_expiry"] = credentials.expiry.isoformat()
        upsert(config)
    return {**config, "password": OAUTH_PASSWORD_PREFIX + (credentials.token or "")}


def resolve(config: dict) -> dict:
    if config.get("auth_type") == "oauth2":
        if config.get("provider") != "gmail":
            raise ValueError("OAuth e-mail n'est pas encore disponible pour ce fournisseur.")
        return _refresh_google(dict(config))
    return dict(config)


def list_resolved() -> list[dict]:
    results = []
    for account in list_raw():
        try:
            results.append(resolve(account))
        except Exception as exc:
            results.append({**account, "_auth_error": str(exc), "password": ""})
    return results


def get(username: str | None = None, *, resolved: bool = True) -> dict | None:
    accounts = list_raw()
    if not accounts:
        return None
    account = accounts[0]
    if username:
        account = next((item for item in accounts
                        if (item.get("username") or "").lower() == username.lower()), None)
    if not account:
        return None
    return resolve(account) if resolved else dict(account)


def public(account: dict) -> dict:
    return {
        "id": account.get("username"),
        "username": account.get("username"),
        "provider": account.get("provider", "custom"),
        "imap_host": account.get("imap_host"),
        "auth_type": account.get("auth_type", "app_password"),
        "oauth_connected": bool(account.get("auth_type") == "oauth2" and account.get("refresh_token")),
        "auth_error": account.get("_auth_error"),
    }
