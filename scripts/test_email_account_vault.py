"""Régressions réelles du coffre DPAPI des comptes e-mail."""
from __future__ import annotations
import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import dpapi_secret_store
import email_account_vault as vault
import email_accounts


def main() -> int:
    audit_events: list[tuple[str, int]] = []
    state: dict[str, object] = {
        "email_accounts": [
            {
                "username": "one@example.test", "provider": "custom",
                "imap_host": "imap.example.test", "smtp_host": "smtp.example.test",
                "password": "first-secret",
            },
            {
                "username": "oauth@example.test", "provider": "gmail",
                "auth_type": "oauth2", "imap_host": "imap.gmail.com",
                "smtp_host": "smtp.gmail.com", "access_token": "access",
                "refresh_token": "refresh", "oauth_client_secret": "client",
            },
        ],
        "email_config": {
            "username": "one@example.test",
            "provider": "custom",
            "imap_host": "imap.example.test",
            "smtp_host": "smtp.example.test",
            "password": "stale-legacy-secret",
        },
    }

    def get_setting(key):
        return state.get(key)

    def set_setting(key, value):
        state[key] = json.loads(json.dumps(value))

    with tempfile.TemporaryDirectory() as directory, patch.object(
        dpapi_secret_store, "PATH", Path(directory) / "email-vault.json"
    ), patch.object(email_accounts.db, "get_setting", side_effect=get_setting), patch.object(
        email_accounts.db, "set_setting", side_effect=set_setting
    ), patch.object(
        email_accounts,
        "_audit_migration",
        side_effect=lambda action, count: audit_events.append((action, count)),
    ):
        assert email_accounts.migrate_legacy_secrets() == 3
        persisted = state["email_accounts"]
        assert isinstance(persisted, list) and len(persisted) == 2
        serialized = json.dumps(persisted)
        for secret in ("first-secret", "access", "refresh", "client"):
            assert secret not in serialized
        assert "stale-legacy-secret" not in json.dumps(state["email_config"])
        assert all(account.get("_secret_ref") for account in persisted)
        resolved = email_accounts.list_raw()
        assert resolved[0]["password"] == "first-secret"
        assert resolved[1]["refresh_token"] == "refresh"

        assert email_accounts.rollback_secrets_to_sqlite(confirmed=True) == 2
        assert "first-secret" in json.dumps(state["email_config"])
        assert email_accounts.migrate_legacy_secrets() == 3
        resolved = email_accounts.list_raw()

        original_persist = email_accounts._persist
        with patch.object(
            email_accounts,
            "_persist",
            side_effect=RuntimeError("database unavailable with private detail"),
        ):
            try:
                email_accounts.upsert({
                    **resolved[0], "password": "must-not-survive",
                })
            except RuntimeError:
                pass
            else:
                raise AssertionError("La panne SQLite devait remonter.")
        assert email_accounts.get(
            "one@example.test", resolved=False
        )["password"] == "first-secret"
        assert email_accounts._persist is original_persist

        updated = {
            **resolved[0], "imap_port": 993, "password": "",
            "auth_type": "app_password",
        }
        email_accounts.upsert(updated)
        assert email_accounts.get("one@example.test", resolved=False)["password"] == "first-secret"

        def add(index: int):
            email_accounts.upsert({
                "username": f"user{index}@example.test",
                "provider": "custom", "imap_host": "imap.example.test",
                "smtp_host": "smtp.example.test", "password": f"secret-{index}",
            })

        with ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(add, range(6)))
        assert len(email_accounts.list_raw()) == 8
        assert len({account["username"] for account in email_accounts.list_raw()}) == 8

        removed_ref = next(
            account["_secret_ref"] for account in state["email_accounts"]
            if account["username"] == "one@example.test"
        )
        with patch.object(vault, "delete", side_effect=RuntimeError("vault unavailable")):
            try:
                email_accounts.remove("one@example.test")
            except RuntimeError:
                pass
            else:
                raise AssertionError("La panne de suppression coffre devait remonter.")
        assert email_accounts.get("one@example.test", resolved=False) is not None
        assert email_accounts.remove("one@example.test") == 1
        assert dpapi_secret_store.has_secret(removed_ref) is False
        assert state["email_config"] == {}

        assert email_accounts.rollback_secrets_to_sqlite(confirmed=True) == 7
        plaintext = json.dumps(state["email_accounts"])
        assert "refresh" in plaintext and "_secret_ref" not in plaintext
        assert email_accounts.migrate_legacy_secrets() == 7

        secret_ref = state["email_accounts"][0]["_secret_ref"]
        rows = json.loads(dpapi_secret_store.PATH.read_text(encoding="utf-8"))
        rows[secret_ref] = "AAAA"
        dpapi_secret_store.PATH.write_text(json.dumps(rows), encoding="utf-8")
        try:
            email_accounts.list_raw()
        except Exception:
            pass
        else:
            raise AssertionError("Une enveloppe DPAPI altérée doit échouer fermé.")
        assert not any(
            vault.extract(account) for account in email_accounts._list_persisted()
        )

    assert audit_events == [
        ("email_account_secrets_migrated", 3),
        ("email_account_secrets_rollback", 2),
        ("email_account_secrets_migrated", 3),
        ("email_account_secrets_rollback", 7),
        ("email_account_secrets_migrated", 7),
    ]
    assert not any(
        secret in repr(audit_events)
        for secret in ("first-secret", "access", "refresh", "client")
    )
    print("Email Account Vault OK - migration, multi-comptes, concurrence, suppression, rollback et corruption.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
