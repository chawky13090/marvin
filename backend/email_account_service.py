"""Frontière de résolution des comptes e-mail utilisée par l'API et les opérations IMAP."""

from __future__ import annotations

import email_accounts


def list_resolved() -> list[dict]:
    return email_accounts.list_resolved()


def get_resolved(account: str | None = None) -> dict | None:
    return email_accounts.get(account, resolved=True)


def list_public() -> dict:
    accounts = email_accounts.list_raw()
    return {
        "accounts": [email_accounts.public(account) for account in accounts],
        "default": accounts[0].get("username") if accounts else None,
        "count": len(accounts),
    }


def upsert_app_password(config: dict) -> list[dict]:
    return email_accounts.upsert({**config, "auth_type": "app_password"})


def remove(account_id: str) -> dict:
    removed = email_accounts.remove(account_id)
    return {
        "success": True,
        "removed": removed,
        "count": len(email_accounts.list_raw()),
    }


def public_config(account: str | None = None) -> dict:
    config = get_resolved(account)
    if not config:
        return {"configured": False}
    secret_fields = {"password", "access_token", "refresh_token", "oauth_client_secret"}
    public = {
        key: value
        for key, value in config.items()
        if key not in secret_fields and not key.startswith("_")
    }
    public["configured"] = True
    public["password_set"] = bool(config.get("password"))
    return public
