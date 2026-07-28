"""Coffre de secrets Marvin : identités opaques et chiffrement DPAPI utilisateur."""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Final

import dpapi_secret_store


_SCOPE: Final = re.compile(r"^[a-z][a-z0-9_-]{1,20}$")
_FIELD: Final = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")


class SecretVaultError(RuntimeError):
    pass


def _key(scope: str, owner: str, field: str) -> str:
    normalized_scope = str(scope or "").strip().casefold()
    normalized_field = str(field or "").strip().casefold()
    normalized_owner = str(owner or "").strip().casefold()
    if (
        not _SCOPE.fullmatch(normalized_scope)
        or not _FIELD.fullmatch(normalized_field)
        or not normalized_owner
        or len(normalized_owner) > 1_024
    ):
        raise SecretVaultError("Identité de secret invalide.")
    digest = hashlib.sha256(normalized_owner.encode("utf-8")).hexdigest()[:32]
    return f"vault.{normalized_scope}.{digest}.{normalized_field}"


def set_secret(scope: str, owner: str, field: str, value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 16_384:
        raise SecretVaultError("Valeur de secret vide ou trop longue.")
    key = _key(scope, owner, field)
    try:
        dpapi_secret_store.set_secret(key, value)
        recovered = dpapi_secret_store.get_secret(key)
    except dpapi_secret_store.SecretStoreError as exc:
        raise SecretVaultError("Le coffre Windows n'a pas pu protéger le secret.") from exc
    if recovered is None or not hmac.compare_digest(recovered, value):
        raise SecretVaultError("La vérification du secret protégé a échoué.")


def get_secret(scope: str, owner: str, field: str) -> str | None:
    try:
        return dpapi_secret_store.get_secret(_key(scope, owner, field))
    except dpapi_secret_store.SecretStoreError as exc:
        raise SecretVaultError("Le coffre Windows n'a pas pu lire le secret.") from exc


def has_secret(scope: str, owner: str, field: str) -> bool:
    try:
        return dpapi_secret_store.has_secret(_key(scope, owner, field))
    except dpapi_secret_store.SecretStoreError as exc:
        raise SecretVaultError("Le coffre Windows n'a pas pu vérifier le secret.") from exc


def delete_secret(scope: str, owner: str, field: str) -> None:
    try:
        dpapi_secret_store.delete_secret(_key(scope, owner, field))
    except dpapi_secret_store.SecretStoreError as exc:
        raise SecretVaultError("Le coffre Windows n'a pas pu supprimer le secret.") from exc
