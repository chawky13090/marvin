"""Coffre DPAPI et migration compensée du compte de service Google."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import audit
import secret_vault


MAX_BYTES: Final = 16_384
LEGACY_PATH = Path(__file__).resolve().parent / "data" / "google_service_account.json"
_SCOPE: Final = "google_sa"
_OWNER: Final = "primary"
_FIELD: Final = "credentials"
_TOKEN_URI: Final = "https://oauth2.googleapis.com/token"
_EMAIL: Final = re.compile(r"^[^@\s]{1,128}@[a-z0-9.-]{1,220}\.iam\.gserviceaccount\.com$")
_LOCK = threading.RLock()


class GoogleServiceAccountVaultError(RuntimeError):
    pass


def _validate_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GoogleServiceAccountVaultError("Le document doit être un objet JSON.")
    required = (
        "type",
        "project_id",
        "private_key_id",
        "private_key",
        "client_email",
        "client_id",
        "token_uri",
    )
    if any(not isinstance(value.get(name), str) or not value[name].strip() for name in required):
        raise GoogleServiceAccountVaultError("La clé de compte de service est incomplète.")
    if value["type"] != "service_account":
        raise GoogleServiceAccountVaultError("Le type Google n'est pas service_account.")
    email = value["client_email"].strip().casefold()
    if not _EMAIL.fullmatch(email):
        raise GoogleServiceAccountVaultError("L'adresse du compte de service est invalide.")
    if value["token_uri"].strip() != _TOKEN_URI:
        raise GoogleServiceAccountVaultError("Le point de terminaison OAuth Google est invalide.")
    try:
        private_key = serialization.load_pem_private_key(
            value["private_key"].encode("ascii"), password=None
        )
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise GoogleServiceAccountVaultError("La clé privée Google est invalide.") from exc
    if not isinstance(private_key, rsa.RSAPrivateKey) or private_key.key_size < 2048:
        raise GoogleServiceAccountVaultError("La clé privée Google doit être RSA 2048 bits ou plus.")
    normalized = dict(value)
    normalized["client_email"] = email
    normalized["token_uri"] = _TOKEN_URI
    return normalized


def _decode(raw: bytes) -> tuple[dict[str, Any], str]:
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise GoogleServiceAccountVaultError("Le fichier Google est vide ou trop volumineux.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoogleServiceAccountVaultError("Le fichier Google n'est pas un JSON UTF-8 valide.") from exc
    payload = _validate_payload(value)
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(canonical.encode("utf-8")) > MAX_BYTES:
        raise GoogleServiceAccountVaultError("La clé Google normalisée est trop volumineuse.")
    return payload, canonical


def _secure_remove(path: Path) -> None:
    if not path.is_file():
        return
    size = path.stat().st_size
    with path.open("r+b", buffering=0) as stream:
        remaining = size
        while remaining > 0:
            chunk_size = min(4096, remaining)
            stream.write(os.urandom(chunk_size))
            remaining -= chunk_size
        stream.flush()
        os.fsync(stream.fileno())
    path.unlink()


def _restrict_legacy_acl(path: Path) -> None:
    if os.name != "nt":
        raise GoogleServiceAccountVaultError("Le rollback du compte Google requiert Windows.")
    username = os.environ.get("USERNAME", "").strip()
    domain = os.environ.get("USERDOMAIN", "").strip()
    if not username or any(char in username + domain for char in "\r\n"):
        raise GoogleServiceAccountVaultError("L'identité Windows courante est introuvable.")
    identity = f"{domain}\\{username}" if domain else username
    completed = subprocess.run(
        [
            "icacls.exe",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{identity}:(F)",
            "/grant:r",
            "*S-1-5-18:(F)",
        ],
        capture_output=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0:
        raise GoogleServiceAccountVaultError("L'ACL du fichier Google de rollback a échoué.")


def _protected_value() -> str | None:
    try:
        return secret_vault.get_secret(_SCOPE, _OWNER, _FIELD)
    except secret_vault.SecretVaultError as exc:
        raise GoogleServiceAccountVaultError("Le coffre Windows Google est indisponible.") from exc


def _set_protected_value(value: str) -> None:
    try:
        secret_vault.set_secret(_SCOPE, _OWNER, _FIELD, value)
    except secret_vault.SecretVaultError as exc:
        raise GoogleServiceAccountVaultError("Le coffre Windows Google est indisponible.") from exc


def _delete_protected_value() -> None:
    try:
        secret_vault.delete_secret(_SCOPE, _OWNER, _FIELD)
    except secret_vault.SecretVaultError as exc:
        raise GoogleServiceAccountVaultError("Le coffre Windows Google est indisponible.") from exc


def store(raw: bytes) -> dict[str, str]:
    payload, canonical = _decode(raw)
    with _LOCK:
        _set_protected_value(canonical)
        recovered = _protected_value()
        if recovered != canonical:
            raise GoogleServiceAccountVaultError("La relecture DPAPI de la clé Google a échoué.")
        if LEGACY_PATH.exists():
            try:
                _secure_remove(LEGACY_PATH)
            except OSError as exc:
                raise GoogleServiceAccountVaultError(
                    "La copie en clair n'a pas pu être supprimée; le coffre reste intact."
                ) from exc
    audit.log_action(
        "google_service_account_store",
        {"storage": "windows_dpapi_current_user"},
        {"success": True, "legacy_removed": not LEGACY_PATH.exists()},
        source="credentials",
    )
    return {"client_email": str(payload["client_email"])}


def migrate_legacy() -> dict[str, Any] | None:
    migrated = False
    with _LOCK:
        protected = _protected_value()
        if protected is not None:
            try:
                payload = _validate_payload(json.loads(protected))
            except (json.JSONDecodeError, TypeError, GoogleServiceAccountVaultError) as exc:
                raise GoogleServiceAccountVaultError("La clé Google protégée est corrompue.") from exc
            canonical = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            if LEGACY_PATH.is_file():
                try:
                    legacy_payload, legacy_canonical = _decode(LEGACY_PATH.read_bytes())
                except OSError as exc:
                    raise GoogleServiceAccountVaultError("La clé Google historique est illisible.") from exc
                if legacy_canonical != canonical:
                    raise GoogleServiceAccountVaultError(
                        "La copie Google en clair diffère du coffre; aucune suppression automatique."
                    )
                payload = legacy_payload
                try:
                    _secure_remove(LEGACY_PATH)
                except OSError as exc:
                    raise GoogleServiceAccountVaultError(
                        "La copie Google historique n'a pas pu être supprimée."
                    ) from exc
                migrated = True
        else:
            if not LEGACY_PATH.is_file():
                return None
            try:
                raw = LEGACY_PATH.read_bytes()
            except OSError as exc:
                raise GoogleServiceAccountVaultError("La clé Google historique est illisible.") from exc
            payload, canonical = _decode(raw)
            _set_protected_value(canonical)
            if _protected_value() != canonical:
                raise GoogleServiceAccountVaultError("La migration DPAPI Google n'est pas relisible.")
            try:
                _secure_remove(LEGACY_PATH)
            except OSError as exc:
                raise GoogleServiceAccountVaultError(
                    "La clé est protégée mais la copie historique n'a pas pu être supprimée."
                ) from exc
            migrated = True
    if migrated:
        audit.log_action(
            "google_service_account_migration",
            {"source": "legacy_file", "storage": "windows_dpapi_current_user"},
            {"success": True, "legacy_removed": True},
            source="migration",
        )
    return payload


def load(*, migrate: bool = True) -> dict[str, Any] | None:
    with _LOCK:
        protected = _protected_value()
        if protected is None:
            return migrate_legacy() if migrate else None
        try:
            return _validate_payload(json.loads(protected))
        except (json.JSONDecodeError, TypeError, GoogleServiceAccountVaultError) as exc:
            raise GoogleServiceAccountVaultError("La clé Google protégée est corrompue.") from exc


def configured() -> bool:
    return load() is not None


def client_email() -> str | None:
    payload = load()
    return str(payload["client_email"]) if payload else None


def delete() -> None:
    with _LOCK:
        if LEGACY_PATH.exists():
            try:
                _secure_remove(LEGACY_PATH)
            except OSError as exc:
                raise GoogleServiceAccountVaultError(
                    "La copie en clair n'a pas pu être supprimée; aucun secret protégé n'a été effacé."
                ) from exc
        _delete_protected_value()
        if _protected_value() is not None:
            raise GoogleServiceAccountVaultError("La suppression DPAPI Google a échoué.")
    audit.log_action(
        "google_service_account_delete",
        {},
        {"success": True, "legacy_removed": True},
        source="credentials",
    )


def restore_legacy_for_rollback(*, acknowledge_plaintext_risk: bool) -> None:
    if not acknowledge_plaintext_risk:
        raise GoogleServiceAccountVaultError(
            "Le rollback doit accepter explicitement le retour temporaire au stockage en clair."
        )
    with _LOCK:
        if LEGACY_PATH.exists():
            raise GoogleServiceAccountVaultError("Le fichier Google historique existe déjà.")
        protected = _protected_value()
        if protected is None:
            raise GoogleServiceAccountVaultError("Aucune clé Google protégée à restaurer.")
        try:
            payload = _validate_payload(json.loads(protected))
        except (json.JSONDecodeError, TypeError, GoogleServiceAccountVaultError) as exc:
            raise GoogleServiceAccountVaultError("La clé Google protégée est corrompue.") from exc
        canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        LEGACY_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = LEGACY_PATH.with_name(f".{LEGACY_PATH.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(canonical)
                stream.flush()
                os.fsync(stream.fileno())
            _restrict_legacy_acl(temporary)
            os.replace(temporary, LEGACY_PATH)
            if LEGACY_PATH.read_text(encoding="utf-8") != canonical:
                raise GoogleServiceAccountVaultError("La vérification du fichier Google restauré a échoué.")
        except (OSError, GoogleServiceAccountVaultError) as exc:
            temporary.unlink(missing_ok=True)
            if LEGACY_PATH.exists():
                try:
                    _secure_remove(LEGACY_PATH)
                except OSError:
                    pass
            if isinstance(exc, GoogleServiceAccountVaultError):
                raise
            raise GoogleServiceAccountVaultError("Le rollback du compte Google a échoué.") from exc
    audit.log_action(
        "google_service_account_rollback",
        {"destination": "legacy_file", "explicit_security_downgrade": True},
        {"success": True, "protected_copy_retained": True},
        source="rollback",
    )


def security_status() -> dict[str, Any]:
    protected = _protected_value() is not None
    legacy = LEGACY_PATH.is_file()
    return {
        "provider": "windows_dpapi_current_user",
        "protected": protected,
        "legacy_plaintext": legacy,
        "migration_complete": protected and not legacy,
    }
