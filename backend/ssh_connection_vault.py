"""Enveloppes DPAPI des secrets persistants de connexions SSH."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import dpapi_secret_store


SECRET_FIELDS = frozenset({"password", "private_key", "key_passphrase"})
_REFERENCE = re.compile(r"^ssh\.connection\.[0-9a-f]{40}$")
_MAX_FIELD = 12_000
_MAX_TOTAL = 15_000


class SSHConnectionVaultError(RuntimeError):
    pass


def reference(connection_id: str) -> str:
    value = connection_id.strip()
    if not value or len(value) > 128:
        raise SSHConnectionVaultError("Identifiant SSH invalide.")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:40]
    return f"ssh.connection.{digest}"


def _validated_reference(value: object) -> str:
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        raise SSHConnectionVaultError("Référence SSH invalide.")
    return value


def extract(config: dict[str, Any]) -> dict[str, str]:
    secrets: dict[str, str] = {}
    for field in SECRET_FIELDS:
        value = config.get(field)
        if value in {None, ""}:
            continue
        if not isinstance(value, str) or len(value) > _MAX_FIELD:
            raise SSHConnectionVaultError(f"Secret SSH invalide : {field}.")
        secrets[field] = value
    if sum(len(value) for value in secrets.values()) > _MAX_TOTAL:
        raise SSHConnectionVaultError("Ensemble de secrets SSH trop volumineux.")
    if not secrets.get("password") and not secrets.get("private_key"):
        raise SSHConnectionVaultError(
            "Un mot de passe ou une clé privée SSH est requis."
        )
    return secrets


def store(connection_id: str, config: dict[str, Any]) -> str:
    secret_ref = reference(connection_id)
    secrets = extract(config)
    payload = json.dumps(
        {
            "schema": 1,
            "connection_hash": secret_ref.rsplit(".", 1)[1],
            "secrets": secrets,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    dpapi_secret_store.set_secret(secret_ref, payload)
    if load(secret_ref) != secrets:
        raise SSHConnectionVaultError("La relecture du secret SSH a échoué.")
    return secret_ref


def load(secret_ref: str) -> dict[str, str]:
    secret_ref = _validated_reference(secret_ref)
    payload = dpapi_secret_store.get_secret(secret_ref)
    if payload is None:
        return {}
    try:
        decoded = json.loads(payload)
    except ValueError as exc:
        raise SSHConnectionVaultError("Enveloppe SSH corrompue.") from exc
    if (
        not isinstance(decoded, dict)
        or decoded.get("schema") != 1
        or decoded.get("connection_hash") != secret_ref.rsplit(".", 1)[1]
        or not isinstance(decoded.get("secrets"), dict)
    ):
        raise SSHConnectionVaultError("Enveloppe SSH invalide.")
    secrets = extract(decoded["secrets"])
    if set(secrets) != set(decoded["secrets"]):
        raise SSHConnectionVaultError("Enveloppe SSH contient un champ interdit.")
    return secrets


def delete(secret_ref: str) -> None:
    dpapi_secret_store.delete_secret(_validated_reference(secret_ref))
