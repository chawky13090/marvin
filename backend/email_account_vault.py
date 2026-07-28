"""Enveloppes DPAPI des secrets de comptes e-mail."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import dpapi_secret_store


SECRET_FIELDS = frozenset({
    "password", "access_token", "refresh_token", "oauth_client_secret",
})
_REFERENCE = re.compile(r"^email\.account\.[0-9a-f]{40}$")
_MAX_SECRET = 12_000
_MAX_SECRET_TOTAL = 15_000


class EmailAccountVaultError(RuntimeError):
    pass


def reference(username: str) -> str:
    normalized = username.strip().casefold()
    if not normalized or len(normalized) > 320:
        raise EmailAccountVaultError("Identité e-mail invalide.")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:40]
    return f"email.account.{digest}"


def _validate_reference(value: object) -> str:
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        raise EmailAccountVaultError("Référence de secret e-mail invalide.")
    return value


def extract(config: dict[str, Any]) -> dict[str, str]:
    secrets: dict[str, str] = {}
    for field in SECRET_FIELDS:
        value = config.get(field)
        if value in {None, ""}:
            continue
        if not isinstance(value, str) or len(value) > _MAX_SECRET:
            raise EmailAccountVaultError(f"Secret e-mail invalide : {field}.")
        secrets[field] = value
    if sum(len(value) for value in secrets.values()) > _MAX_SECRET_TOTAL:
        raise EmailAccountVaultError("Ensemble de secrets e-mail trop volumineux.")
    return secrets


def sanitized(config: dict[str, Any], secret_ref: str) -> dict[str, Any]:
    clean = {
        key: value for key, value in config.items()
        if key not in SECRET_FIELDS and not key.startswith("_secret_")
    }
    clean["_secret_ref"] = _validate_reference(secret_ref)
    clean["_secret_version"] = 1
    return clean


def store(config: dict[str, Any]) -> str:
    username = str(config.get("username") or "")
    secret_ref = reference(username)
    secrets = extract(config)
    if not secrets:
        existing = load(secret_ref)
        if existing:
            return secret_ref
        raise EmailAccountVaultError("Aucun secret e-mail à protéger.")
    payload = json.dumps(
        {"schema": 1, "username_hash": secret_ref.rsplit(".", 1)[1], "secrets": secrets},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    dpapi_secret_store.set_secret(secret_ref, payload)
    if load(secret_ref) != secrets:
        raise EmailAccountVaultError("La relecture du secret e-mail a échoué.")
    return secret_ref


def load(secret_ref: str) -> dict[str, str]:
    secret_ref = _validate_reference(secret_ref)
    payload = dpapi_secret_store.get_secret(secret_ref)
    if payload is None:
        return {}
    try:
        decoded = json.loads(payload)
    except ValueError as exc:
        raise EmailAccountVaultError("Enveloppe e-mail corrompue.") from exc
    if (
        not isinstance(decoded, dict)
        or decoded.get("schema") != 1
        or decoded.get("username_hash") != secret_ref.rsplit(".", 1)[1]
        or not isinstance(decoded.get("secrets"), dict)
    ):
        raise EmailAccountVaultError("Enveloppe e-mail invalide.")
    secrets = extract(decoded["secrets"])
    if set(secrets) != set(decoded["secrets"]):
        raise EmailAccountVaultError("Enveloppe e-mail contient un champ interdit.")
    return secrets


def delete(secret_ref: str) -> None:
    dpapi_secret_store.delete_secret(_validate_reference(secret_ref))
