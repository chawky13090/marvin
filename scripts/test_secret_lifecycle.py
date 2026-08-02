"""Régressions du cycle de vie et de la portabilité du coffre DPAPI."""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import dpapi_secret_store as store
import secret_lifecycle
import audit


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="marvin-secret-lifecycle-") as directory:
        vault = Path(directory) / "windows_secrets.dpapi.json"
        audit_events: list[tuple[tuple, dict]] = []
        with (
            patch.object(store, "PATH", vault),
            patch.object(store, "_DEFAULT_PATH", vault),
            patch.object(
                audit,
                "log_action",
                side_effect=lambda *args, **kwargs: audit_events.append((args, kwargs)),
            ),
        ):
            store.set_secret("vault.credential.abc.value", "never-in-metadata")
            metadata_path = secret_lifecycle.metadata_path(vault)
            metadata_text = metadata_path.read_text(encoding="utf-8")
            assert "never-in-metadata" not in metadata_text
            first = json.loads(metadata_text)["entries"]["vault.credential.abc.value"]
            assert first["state"] == "active" and first["revision"] == 1
            assert first["category"] == "credential"
            assert first["review_after_days"] == 180

            store.set_secret("vault.credential.abc.value", "rotated-value")
            second = json.loads(metadata_path.read_text(encoding="utf-8"))["entries"][
                "vault.credential.abc.value"
            ]
            assert second["created_at"] == first["created_at"]
            assert second["revision"] == 2 and second["rotated_at"] >= first["rotated_at"]

            expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
            store.set_secret("vault.oauthlegacy.abc.access", "expired-token", expires_at=expired)
            try:
                store.get_secret("vault.oauthlegacy.abc.access")
            except store.SecretStoreError as exc:
                assert "expir" in str(exc).casefold() and "expired-token" not in str(exc)
            else:
                raise AssertionError("Un secret expiré doit échouer fermé.")

            store.delete_secret("vault.credential.abc.value")
            revoked = json.loads(metadata_path.read_text(encoding="utf-8"))["entries"][
                "vault.credential.abc.value"
            ]
            assert revoked["state"] == "revoked" and revoked["revoked_at"]
            assert store.get_secret("vault.credential.abc.value") is None

            status = store.lifecycle_status(verify_decryption=True)
            assert status["active"] == 1 and status["expired"] == 1
            assert status["review_due"] == 0
            assert status["portable"] is False and status["unreadable"] == 0

            # Un coffre copié/altéré ne livre aucun secret et demande une réauthentification.
            rows = json.loads(vault.read_text(encoding="utf-8"))
            rows["vault.oauthlegacy.abc.access"] = base64.b64encode(b"not-dpapi").decode("ascii")
            vault.write_text(json.dumps(rows), encoding="utf-8")
            portability = store.lifecycle_status(verify_decryption=True)
            assert portability["unreadable"] == 1
            assert portability["reauthentication_required"] is True
            assert "réenregistrer" in portability["migration_guidance"]

            # Une corruption de métadonnées est fail-closed sans modifier le ciphertext.
            ciphertext_before = vault.read_bytes()
            valid_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            valid_metadata["entries"]["vault.oauthlegacy.abc.access"]["expires_at"] = "invalid"
            metadata_path.write_text(json.dumps(valid_metadata), encoding="utf-8")
            try:
                store.lifecycle_status()
            except secret_lifecycle.SecretLifecycleError:
                pass
            else:
                raise AssertionError("Une expiration invalide doit bloquer la lecture.")
            metadata_path.write_text("{invalid", encoding="utf-8")
            try:
                store.has_secret("vault.oauthlegacy.abc.access")
            except secret_lifecycle.SecretLifecycleError:
                pass
            else:
                raise AssertionError("Un registre de cycle de vie corrompu doit bloquer la lecture.")
            assert vault.read_bytes() == ciphertext_before

        serialized_audit = repr(audit_events)
        assert "never-in-metadata" not in serialized_audit
        assert "rotated-value" not in serialized_audit
        assert "expired-token" not in serialized_audit
        assert any(args[0] == "secret_created" for args, _ in audit_events)
        assert any(args[0] == "secret_rotated" for args, _ in audit_events)
        assert any(args[0] == "secret_revoked" for args, _ in audit_events)

        # Migration transparente d'un coffre historique sans métadonnées.
        legacy_vault = Path(directory) / "legacy" / "windows_secrets.dpapi.json"
        legacy_vault.parent.mkdir()
        protected = base64.b64encode(store._crypt(b"legacy-secret", protect=True)).decode("ascii")
        legacy_vault.write_text(
            json.dumps({"vault.credential.legacy.value": protected}), encoding="utf-8"
        )
        with patch.object(store, "PATH", legacy_vault):
            legacy_status = store.lifecycle_status(verify_decryption=True)
            assert legacy_status["active"] == 1 and legacy_status["unreadable"] == 0
            migrated = json.loads(
                secret_lifecycle.metadata_path(legacy_vault).read_text(encoding="utf-8")
            )
            assert migrated["entries"]["vault.credential.legacy.value"]["origin"] == "inferred_from_vault_mtime"

        # Une panne du compagnon restaure le ciphertext lors d'une rotation ou révocation.
        atomic_vault = Path(directory) / "atomic" / "windows_secrets.dpapi.json"
        atomic_vault.parent.mkdir()
        with patch.object(store, "PATH", atomic_vault):
            store.set_secret("vault.credential.atomic.value", "before")
            ciphertext_before = atomic_vault.read_bytes()
            metadata_before = secret_lifecycle.metadata_path(atomic_vault).read_bytes()
            for operation in ("rotate", "revoke"):
                with patch.object(
                    secret_lifecycle,
                    "write",
                    side_effect=secret_lifecycle.SecretLifecycleError("simulated"),
                ):
                    try:
                        if operation == "rotate":
                            store.set_secret("vault.credential.atomic.value", "after")
                        else:
                            store.delete_secret("vault.credential.atomic.value")
                    except secret_lifecycle.SecretLifecycleError:
                        pass
                    else:
                        raise AssertionError("La panne des métadonnées doit être propagée.")
                assert atomic_vault.read_bytes() == ciphertext_before
                assert secret_lifecycle.metadata_path(atomic_vault).read_bytes() == metadata_before
                assert store.get_secret("vault.credential.atomic.value") == "before"

    print("Secret Lifecycle OK - création, rotation, expiration, révocation et réauthentification DPAPI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
