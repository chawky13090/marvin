"""Contrat de protection de la clé de compte de service Google."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import google_service_account_vault as vault


def _payload() -> dict[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return {
        "type": "service_account",
        "project_id": "marvin-test",
        "private_key_id": "a" * 40,
        "private_key": pem,
        "client_email": "marvin@marvin-test.iam.gserviceaccount.com",
        "client_id": "1234567890",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def main() -> int:
    protected: dict[tuple[str, str, str], str] = {}

    def set_secret(scope: str, owner: str, field: str, value: str) -> None:
        protected[(scope, owner, field)] = value

    def get_secret(scope: str, owner: str, field: str) -> str | None:
        return protected.get((scope, owner, field))

    def delete_secret(scope: str, owner: str, field: str) -> None:
        protected.pop((scope, owner, field), None)

    with tempfile.TemporaryDirectory(prefix="marvin-google-sa-") as directory:
        legacy = Path(directory) / "google_service_account.json"
        with (
            patch.object(vault, "LEGACY_PATH", legacy),
            patch.object(vault.secret_vault, "set_secret", side_effect=set_secret),
            patch.object(vault.secret_vault, "get_secret", side_effect=get_secret),
            patch.object(vault.secret_vault, "delete_secret", side_effect=delete_secret),
            patch.object(vault.audit, "log_action"),
        ):
            saved = vault.store(json.dumps(_payload()).encode("utf-8"))
            assert saved["client_email"].endswith(".iam.gserviceaccount.com")
            assert vault.load()["project_id"] == "marvin-test"
            assert not legacy.exists()

            try:
                vault.restore_legacy_for_rollback(acknowledge_plaintext_risk=False)
            except vault.GoogleServiceAccountVaultError:
                pass
            else:
                raise AssertionError("Le rollback en clair ne doit jamais être implicite.")

            with patch.object(vault, "_restrict_legacy_acl") as restrict_acl:
                vault.restore_legacy_for_rollback(acknowledge_plaintext_risk=True)
            assert legacy.is_file()
            assert json.loads(legacy.read_text(encoding="utf-8"))["project_id"] == "marvin-test"
            restrict_acl.assert_called_once()
            migrated_again = vault.migrate_legacy()
            assert migrated_again and not legacy.exists()

            divergent = _payload()
            divergent["project_id"] = "different-project"
            legacy.write_text(json.dumps(divergent), encoding="utf-8")
            try:
                vault.migrate_legacy()
            except vault.GoogleServiceAccountVaultError:
                pass
            else:
                raise AssertionError("Deux copies Google divergentes ne doivent pas être fusionnées.")
            assert legacy.exists()

            vault.delete()
            assert vault.load(migrate=False) is None

            with patch.object(
                vault.secret_vault,
                "get_secret",
                side_effect=vault.secret_vault.SecretVaultError("offline"),
            ):
                try:
                    vault.load(migrate=False)
                except vault.GoogleServiceAccountVaultError:
                    pass
                else:
                    raise AssertionError("Une panne du coffre ne doit pas être masquée.")

            legacy.write_text(json.dumps(_payload()), encoding="utf-8")
            migrated = vault.load()
            assert migrated and migrated["project_id"] == "marvin-test"
            assert not legacy.exists()

            legacy.write_text(json.dumps(_payload()), encoding="utf-8")
            with patch.object(vault, "_secure_remove", side_effect=OSError("blocked")):
                try:
                    vault.delete()
                except vault.GoogleServiceAccountVaultError:
                    pass
                else:
                    raise AssertionError("Une suppression partielle ne doit pas réussir.")
            assert vault.load(migrate=False) is not None

            bad = _payload()
            bad["token_uri"] = "http://attacker.test/token"
            try:
                vault.store(json.dumps(bad).encode("utf-8"))
            except vault.GoogleServiceAccountVaultError:
                pass
            else:
                raise AssertionError("token_uri non fiable accepté")

            try:
                vault.store(b"{" + b"x" * vault.MAX_BYTES)
            except vault.GoogleServiceAccountVaultError:
                pass
            else:
                raise AssertionError("Fichier surdimensionné accepté")

    print("Google Service Account Vault OK - DPAPI, migration, validation et compensation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
