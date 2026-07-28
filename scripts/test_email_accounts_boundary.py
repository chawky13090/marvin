"""Régressions de la frontière API de gestion des comptes e-mail."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import patch
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import email_account_service as service


def main() -> int:
    raw = {
        "username": "user@example.test",
        "provider": "custom",
        "password": "secret",
        "access_token": "token",
        "refresh_token": "refresh",
        "oauth_client_secret": "client-secret",
        "_runtime": "internal",
    }
    with patch.object(service, "get_resolved", return_value=raw):
        public = service.public_config("user@example.test")
    assert public["configured"] is True and public["password_set"] is True
    for secret in ("password", "access_token", "refresh_token", "oauth_client_secret", "_runtime"):
        assert secret not in public

    with patch.object(service.email_accounts, "list_raw", return_value=[raw]), patch.object(
        service.email_accounts, "public", return_value={"username": raw["username"]}
    ):
        listing = service.list_public()
    assert listing == {
        "accounts": [{"username": "user@example.test"}],
        "default": "user@example.test",
        "count": 1,
    }

    with patch.object(service.email_accounts, "upsert", return_value=[raw]) as upsert:
        saved = service.upsert_app_password({"username": raw["username"]})
    assert saved == [raw]
    assert upsert.call_args.args[0]["auth_type"] == "app_password"

    import main
    from api.email_accounts import EmailConfig

    for invalid in (
        {
            "imap_host": "imap.example.test", "smtp_host": "smtp.example.test",
            "username": "u@example.test", "password": "x", "imap_port": 0,
        },
        {
            "imap_host": "imap.example.test", "smtp_host": "smtp.example.test",
            "username": "u@example.test", "password": "x" * 12_001,
        },
    ):
        try:
            EmailConfig(**invalid)
        except ValidationError:
            pass
        else:
            raise AssertionError("La configuration e-mail hors limites doit être refusée.")

    expected = {
        ("/api/email/providers", "GET"),
        ("/api/email/config", "GET"),
        ("/api/email/config", "POST"),
        ("/api/email/accounts", "GET"),
        ("/api/email/accounts", "POST"),
        ("/api/email/accounts/{account_id}", "DELETE"),
        ("/api/email/test", "POST"),
    }
    observed: set[tuple[str, str]] = set()
    for route in main.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/email"):
            continue
        endpoint = getattr(route, "endpoint", None)
        methods = getattr(route, "methods", set())
        for method in methods:
            pair = (path, method)
            if pair in expected:
                assert endpoint.__module__ == "api.email_accounts", pair
                observed.add(pair)
    assert observed == expected, sorted(expected - observed)
    source = inspect.getsource(main)
    assert "class EmailConfig" not in source
    assert "async def email_accounts_add" not in source
    print("Email Accounts Boundary OK - secrets masqués, multi-comptes et 7 contrats API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
