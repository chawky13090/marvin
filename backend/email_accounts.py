"""Stockage et résolution des identités e-mail, mot de passe ou OAuth2.

Le marqueur OAuth n'est jamais persisté : il est construit à la demande pour les
adaptateurs IMAP/SMTP après rafraîchissement du jeton.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import database as db

OAUTH_PASSWORD_PREFIX = "__MARVIN_OAUTH2__:"


def _coerce(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return None
    return value


def list_raw() -> list[dict]:
    accounts = _coerce(db.get_setting("email_accounts"))
    if not isinstance(accounts, list):
        accounts = []
    if not accounts:
        legacy = _coerce(db.get_setting("email_config"))
        if isinstance(legacy, dict) and legacy.get("imap_host"):
            accounts = [legacy]
            save(accounts)
    return [dict(account) for account in accounts
            if isinstance(account, dict) and account.get("username")]


def save(accounts: list[dict]) -> None:
    db.set_setting("email_accounts", accounts)


def upsert(config: dict) -> list[dict]:
    accounts = list_raw()
    username = (config.get("username") or "").strip()
    index = next((i for i, account in enumerate(accounts)
                  if (account.get("username") or "").lower() == username.lower()), None)
    if index is None:
        accounts.append(dict(config))
    else:
        merged = {**accounts[index], **config}
        # Un formulaire vide conserve le secret existant.
        if not config.get("password") and accounts[index].get("password") and config.get("auth_type") != "oauth2":
            merged["password"] = accounts[index]["password"]
        if config.get("auth_type") == "oauth2" and not config.get("refresh_token") and accounts[index].get("refresh_token"):
            merged["refresh_token"] = accounts[index]["refresh_token"]
        accounts[index] = merged
    save(accounts)
    return accounts


def remove(username: str) -> int:
    accounts = list_raw()
    remaining = [account for account in accounts
                 if (account.get("username") or "").lower() != username.lower()]
    save(remaining)
    return len(accounts) - len(remaining)


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
