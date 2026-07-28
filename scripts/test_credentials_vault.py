"""Régressions du coffre DPAPI et de la migration des identifiants globaux."""

from __future__ import annotations

import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import credentials_manager
import dpapi_secret_store
import secret_vault


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        vault_path = Path(directory) / "secrets.dpapi.json"
        settings: dict[str, object] = {}

        def get_setting(key: str, default=None):
            return settings.get(key, default)

        def set_setting(key: str, value) -> None:
            settings[key] = value

        with (
            patch.object(dpapi_secret_store, "PATH", vault_path),
            patch.object(credentials_manager.db, "get_setting", side_effect=get_setting),
            patch.object(credentials_manager.db, "set_setting", side_effect=set_setting),
            patch.object(credentials_manager.audit, "log_action"),
        ):
            legacy_secret = "legacy-value-never-written-in-clear"
            settings["cred_google_client_secret"] = legacy_secret

            assert credentials_manager.get_credential("google_client_secret") == legacy_secret
            assert settings["cred_google_client_secret"] is None
            assert legacy_secret not in vault_path.read_text(encoding="utf-8")
            assert credentials_manager.security_status()["legacy_plaintext"] == 0
            assert credentials_manager.security_status()["encrypted"] == 1

            # Une écriture tardive par une ancienne version gagne sans perte.
            settings["cred_google_client_secret"] = "newer-legacy-value"
            assert (
                credentials_manager.get_credential("google_client_secret")
                == "newer-legacy-value"
            )
            assert settings["cred_google_client_secret"] is None
            assert (
                secret_vault.get_secret(
                    "credential", "google_client_secret", "value"
                )
                == "newer-legacy-value"
            )

            credentials_manager.set_credential("brave_search_api_key", "brave-private")
            assert credentials_manager.get_credential("brave_search_api_key") == "brave-private"
            assert settings["cred_brave_search_api_key"] is None
            public = credentials_manager.get_all_credentials()["brave_search_api_key"]
            assert public["has_value"] is True and public["value"] == ""

            credentials_manager.set_credential("searxng_url", "http://localhost:8080")
            assert settings["cred_searxng_url"] == "http://localhost:8080"
            assert credentials_manager.get_credential("searxng_url") == "http://localhost:8080"

            # Les propriétaires ne sont pas persistés en clair dans les clés du coffre.
            serialized = vault_path.read_text(encoding="utf-8")
            assert "google_client_secret" not in serialized
            assert "brave_search_api_key" not in serialized

            def write_concurrently(index: int) -> None:
                secret_vault.set_secret("credential", f"owner-{index}", "value", f"value-{index}")

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(write_concurrently, range(20)))
            rows = json.loads(vault_path.read_text(encoding="utf-8"))
            assert len(rows) == 22
            for index in range(20):
                assert (
                    secret_vault.get_secret("credential", f"owner-{index}", "value")
                    == f"value-{index}"
                )

            # Le rollback réhydrate SQLite après vérification, puis retire le secret protégé.
            result = credentials_manager.restore_legacy_plaintext(
                confirmed=True,
                delete_protected=True,
            )
            assert result["restored"] == 2
            assert settings["cred_google_client_secret"] == "newer-legacy-value"
            assert settings["cred_brave_search_api_key"] == "brave-private"
            assert not secret_vault.has_secret(
                "credential", "google_client_secret", "value"
            )

            # Une corruption est fail-closed et ne nettoie jamais la copie historique.
            settings["cred_google_client_secret"] = legacy_secret
            vault_path.write_text("{not-json", encoding="utf-8")
            try:
                credentials_manager.get_credential("google_client_secret")
            except secret_vault.SecretVaultError as exc:
                assert legacy_secret not in str(exc)
            else:
                raise AssertionError("Un coffre corrompu doit bloquer la lecture.")
            assert settings["cred_google_client_secret"] == legacy_secret
            assert vault_path.read_text(encoding="utf-8") == "{not-json"

            try:
                credentials_manager.restore_legacy_plaintext(confirmed=False)
            except ValueError:
                pass
            else:
                raise AssertionError("Le rollback doit exiger une confirmation explicite.")

            try:
                credentials_manager.set_credential("unknown", "value")
            except ValueError:
                pass
            else:
                raise AssertionError("Un identifiant inconnu doit être refusé.")
            assert "glpi_url" in credentials_manager.CREDENTIAL_DEFINITIONS
            assert credentials_manager.CREDENTIAL_DEFINITIONS["glpi_app_token"]["secret"]

    print("Coffre DPAPI et migration des identifiants globaux : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
