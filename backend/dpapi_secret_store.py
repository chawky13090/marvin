"""Small Windows DPAPI-backed secret store; ciphertext only is persisted on disk."""
from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import sys
import threading
from ctypes import wintypes
from pathlib import Path

from config import DATA_DIR


PATH = Path(DATA_DIR) / "windows_secrets.dpapi.json"
_LOCK = threading.RLock()
_KEY = re.compile(r"^[a-z][a-z0-9_.-]{1,80}$")
_DESCRIPTION = "Marvin Test Forge"
_ENTROPY = b"marvin-test-forge-v1"


class SecretStoreError(RuntimeError):
    pass


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(value: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(value)
    return _DATA_BLOB(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _crypt(value: bytes, *, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise SecretStoreError("DPAPI est disponible uniquement sous Windows.")
    source, source_buffer = _blob(value)
    entropy, entropy_buffer = _blob(_ENTROPY)
    destination = _DATA_BLOB()
    description = wintypes.LPWSTR()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(source), _DESCRIPTION, ctypes.byref(entropy), None, None,
            0x1, ctypes.byref(destination),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source), ctypes.byref(description), ctypes.byref(entropy), None, None,
            0x1, ctypes.byref(destination),
        )
    _ = source_buffer, entropy_buffer
    if not ok:
        raise SecretStoreError(f"DPAPI a échoué avec le code Windows {ctypes.get_last_error()}.")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree(destination.pbData)
        if description:
            kernel32.LocalFree(description)


def _load() -> dict[str, str]:
    try:
        value = json.loads(PATH.read_text(encoding="utf-8"))
        return {str(key): str(item) for key, item in value.items()} if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(value: dict[str, str]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, PATH)


def set_secret(key: str, value: str) -> None:
    if not _KEY.fullmatch(key):
        raise SecretStoreError("Nom de secret invalide.")
    if not value or len(value) > 16_384:
        raise SecretStoreError("Valeur de secret vide ou trop longue.")
    encrypted = base64.b64encode(_crypt(value.encode("utf-8"), protect=True)).decode("ascii")
    with _LOCK:
        rows = _load()
        rows[key] = encrypted
        _write(rows)


def get_secret(key: str) -> str | None:
    if not _KEY.fullmatch(key):
        raise SecretStoreError("Nom de secret invalide.")
    encoded = _load().get(key)
    if not encoded:
        return None
    try:
        return _crypt(base64.b64decode(encoded, validate=True), protect=False).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise SecretStoreError("Secret DPAPI illisible pour ce compte Windows.") from exc


def has_secret(key: str) -> bool:
    return key in _load()


def delete_secret(key: str) -> None:
    with _LOCK:
        rows = _load()
        rows.pop(key, None)
        _write(rows)
