"""Métadonnées non sensibles et bornées du cycle de vie des secrets Marvin."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
MAX_ENTRIES = 4_096
REVOKED_RETENTION_DAYS = 365
_KEY = re.compile(r"^[a-z][a-z0-9_.-]{1,80}$")


class SecretLifecycleError(RuntimeError):
    pass


def metadata_path(vault_path: Path) -> Path:
    return vault_path.with_name("windows_secrets.metadata.json")


def _now_iso(now: float | None = None) -> str:
    return datetime.fromtimestamp(now if now is not None else time.time(), UTC).isoformat()


def _parse_timestamp(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def category(key: str) -> str:
    if key.startswith("email.account."):
        return "email_account"
    if key.startswith("ssh.connection."):
        return "ssh_connection"
    if key.startswith("vault.google_sa."):
        return "google_service_account"
    if key.startswith("vault.oauthlegacy."):
        return "oauth"
    if key.startswith("vault.credential."):
        return "credential"
    if key.startswith("vault.lanaccess."):
        return "lan_access"
    if key.startswith(("vm.", "hyperv.", "testforge.")):
        return "test_environment"
    return "internal"


def review_after_days(secret_category: str) -> int:
    return {
        "test_environment": 30,
        "oauth": 90,
        "google_service_account": 180,
        "credential": 180,
        "ssh_connection": 180,
        "email_account": 365,
        "lan_access": 365,
        "internal": 365,
    }.get(secret_category, 365)


def _empty() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "windows_dpapi_current_user",
        "portable": False,
        "entries": {},
    }


def load(vault_path: Path) -> dict[str, Any]:
    path = metadata_path(vault_path)
    if not path.exists():
        return _empty()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SecretLifecycleError("Le registre de cycle de vie des secrets est corrompu.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("provider") != "windows_dpapi_current_user"
        or payload.get("portable") is not False
        or not isinstance(payload.get("entries"), dict)
        or len(payload["entries"]) > MAX_ENTRIES
    ):
        raise SecretLifecycleError("Le registre de cycle de vie des secrets est invalide.")
    for key, entry in payload["entries"].items():
        if not isinstance(key, str) or not _KEY.fullmatch(key) or not isinstance(entry, dict):
            raise SecretLifecycleError("Une métadonnée de secret est invalide.")
        if entry.get("state") not in {"active", "revoked"}:
            raise SecretLifecycleError("Un état de secret est invalide.")
        if not isinstance(entry.get("revision"), int) or entry["revision"] < 1:
            raise SecretLifecycleError("Une révision de secret est invalide.")
        if _parse_timestamp(entry.get("created_at")) is None:
            raise SecretLifecycleError("Une date de création de secret est invalide.")
        if _parse_timestamp(entry.get("rotated_at")) is None:
            raise SecretLifecycleError("Une date de rotation de secret est invalide.")
        if entry.get("expires_at") is not None and _parse_timestamp(entry["expires_at"]) is None:
            raise SecretLifecycleError("Une date d'expiration de secret est invalide.")
        if entry["state"] == "revoked" and _parse_timestamp(entry.get("revoked_at")) is None:
            raise SecretLifecycleError("Une date de révocation de secret est invalide.")
        review_days = entry.get("review_after_days")
        if review_days is not None and (
            not isinstance(review_days, int) or isinstance(review_days, bool) or not 1 <= review_days <= 3_650
        ):
            raise SecretLifecycleError("Une échéance de revue de secret est invalide.")
    return payload


def write(vault_path: Path, payload: dict[str, Any]) -> None:
    path = metadata_path(vault_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_entries(
    payload: dict[str, Any], keys: set[str], *, inferred_at: float
) -> bool:
    entries = payload["entries"]
    changed = False
    timestamp = _now_iso(inferred_at)
    for key in sorted(keys):
        if key not in entries:
            secret_category = category(key)
            entries[key] = {
                "category": secret_category,
                "state": "active",
                "created_at": timestamp,
                "rotated_at": timestamp,
                "revoked_at": None,
                "expires_at": None,
                "revision": 1,
                "origin": "inferred_from_vault_mtime",
                "review_after_days": review_after_days(secret_category),
            }
            changed = True
        else:
            secret_category = category(key)
            if entries[key].get("category") != secret_category:
                entries[key]["category"] = secret_category
                changed = True
            if entries[key].get("review_after_days") != review_after_days(secret_category):
                entries[key]["review_after_days"] = review_after_days(secret_category)
                changed = True
    return changed


def record_set(
    payload: dict[str, Any], key: str, *, expires_at: str | None = None, now: float | None = None
) -> None:
    timestamp = _now_iso(now)
    existing = payload["entries"].get(key)
    if existing is None and len(payload["entries"]) >= MAX_ENTRIES:
        raise SecretLifecycleError("Le registre de cycle de vie des secrets a atteint sa limite.")
    created_at = existing.get("created_at") if isinstance(existing, dict) else timestamp
    revision = int(existing.get("revision", 0)) + 1 if isinstance(existing, dict) else 1
    if expires_at is not None and _parse_timestamp(expires_at) is None:
        raise SecretLifecycleError("La date d'expiration du secret est invalide.")
    secret_category = category(key)
    payload["entries"][key] = {
        "category": secret_category,
        "state": "active",
        "created_at": created_at,
        "rotated_at": timestamp,
        "revoked_at": None,
        "expires_at": expires_at,
        "revision": revision,
        "origin": "recorded",
        "review_after_days": review_after_days(secret_category),
    }


def record_revocation(payload: dict[str, Any], key: str, *, now: float | None = None) -> None:
    timestamp = _now_iso(now)
    existing = payload["entries"].get(key)
    if existing is None and len(payload["entries"]) >= MAX_ENTRIES:
        raise SecretLifecycleError("Le registre de cycle de vie des secrets a atteint sa limite.")
    if not isinstance(existing, dict):
        existing = {
            "category": category(key),
            "created_at": timestamp,
            "rotated_at": timestamp,
            "revision": 1,
            "origin": "recorded",
        }
    payload["entries"][key] = {
        **existing,
        "state": "revoked",
        "revoked_at": timestamp,
        "expires_at": existing.get("expires_at"),
    }
    cutoff = (now if now is not None else time.time()) - REVOKED_RETENTION_DAYS * 86_400
    payload["entries"] = {
        item_key: item
        for item_key, item in payload["entries"].items()
        if item.get("state") != "revoked"
        or (_parse_timestamp(item.get("revoked_at")) or cutoff) >= cutoff
    }


def is_expired(entry: dict[str, Any], *, now: float | None = None) -> bool:
    expires = _parse_timestamp(entry.get("expires_at"))
    return expires is not None and expires <= (now if now is not None else time.time())


def summarize(payload: dict[str, Any], active_keys: set[str], *, now: float | None = None) -> dict[str, Any]:
    current = now if now is not None else time.time()
    entries = payload["entries"]
    active = [entries[key] for key in active_keys if key in entries]
    expired = [entry for entry in active if is_expired(entry, now=current)]
    review_due = [
        entry
        for entry in active
        if (_parse_timestamp(entry.get("rotated_at")) or current)
        + int(entry.get("review_after_days") or 365) * 86_400
        <= current
    ]
    categories: dict[str, int] = {}
    for entry in active:
        name = str(entry.get("category") or "internal")
        categories[name] = categories.get(name, 0) + 1
    return {
        "provider": "windows_dpapi_current_user",
        "portable": False,
        "active": len(active_keys),
        "revoked_metadata": sum(1 for item in entries.values() if item.get("state") == "revoked"),
        "expired": len(expired),
        "review_due": len(review_due),
        "categories": categories,
        "reauthentication_required": False,
        "unreadable": 0,
        "migration_guidance": (
            "Les secrets DPAPI ne migrent pas avec data. Reconnecter les comptes et "
            "réenregistrer les identifiants sur le PC cible."
        ),
    }
