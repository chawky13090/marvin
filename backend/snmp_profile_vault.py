"""Coffre DPAPI des secrets SNMPv3, jamais exposés au registre d'outils."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import dpapi_secret_store

_REFERENCE = re.compile(r"^snmp\.profile\.[0-9a-f]{40}$")
_FIELDS = frozenset({"auth_key", "priv_key"})
_MAX_SECRET = 1024


class SNMPProfileVaultError(RuntimeError):
    pass


def reference(profile_id: str) -> str:
    value = str(profile_id or "").strip()
    if not value or len(value) > 128:
        raise SNMPProfileVaultError("Identifiant de profil SNMP invalide.")
    return f"snmp.profile.{hashlib.sha256(value.encode('utf-8')).hexdigest()[:40]}"


def _validate_reference(value: object) -> str:
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        raise SNMPProfileVaultError("Référence de profil SNMP invalide.")
    return value


def _validate(secrets: dict[str, Any]) -> dict[str, str]:
    if set(secrets) - _FIELDS:
        raise SNMPProfileVaultError("Champ secret SNMP interdit.")
    result: dict[str, str] = {}
    for field in _FIELDS:
        value = secrets.get(field)
        if value in {None, ""}:
            continue
        if not isinstance(value, str) or not 8 <= len(value) <= _MAX_SECRET:
            raise SNMPProfileVaultError(f"Le secret {field} doit contenir entre 8 et {_MAX_SECRET} caractères.")
        result[field] = value
    if "priv_key" in result and "auth_key" not in result:
        raise SNMPProfileVaultError("Une clé privacy exige une clé auth SNMPv3.")
    return result


def store(profile_id: str, secrets: dict[str, Any]) -> str:
    secret_ref = reference(profile_id)
    validated = _validate(secrets)
    payload = json.dumps({"schema": 1, "profile_hash": secret_ref.rsplit('.', 1)[1], "secrets": validated}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    dpapi_secret_store.set_secret(secret_ref, payload)
    if load(secret_ref) != validated:
        raise SNMPProfileVaultError("La relecture du secret SNMPv3 a échoué.")
    return secret_ref


def load(secret_ref: str) -> dict[str, str]:
    validated_ref = _validate_reference(secret_ref)
    payload = dpapi_secret_store.get_secret(validated_ref)
    if payload is None:
        return {}
    try:
        decoded = json.loads(payload)
    except ValueError as exc:
        raise SNMPProfileVaultError("Enveloppe SNMPv3 corrompue.") from exc
    if not isinstance(decoded, dict) or decoded.get("schema") != 1 or decoded.get("profile_hash") != validated_ref.rsplit('.', 1)[1] or not isinstance(decoded.get("secrets"), dict):
        raise SNMPProfileVaultError("Enveloppe SNMPv3 invalide.")
    return _validate(decoded["secrets"])


def delete(secret_ref: str) -> None:
    dpapi_secret_store.delete_secret(_validate_reference(secret_ref))
