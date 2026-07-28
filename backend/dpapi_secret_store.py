"""Small Windows DPAPI-backed secret store; ciphertext only is persisted on disk."""
from __future__ import annotations

import base64
import ctypes
import json
import hashlib
import os
import re
import sys
import threading
import time
import uuid
from contextlib import contextmanager
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
    return _crypt_with_context(
        value,
        protect=protect,
        entropy=_ENTROPY,
        description=_DESCRIPTION,
    )


def _crypt_with_context(
    value: bytes,
    *,
    protect: bool,
    entropy: bytes,
    description: str,
) -> bytes:
    if sys.platform != "win32":
        raise SecretStoreError("DPAPI est disponible uniquement sous Windows.")
    source, source_buffer = _blob(value)
    entropy_blob, entropy_buffer = _blob(entropy)
    destination = _DATA_BLOB()
    returned_description = wintypes.LPWSTR()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(source), description, ctypes.byref(entropy_blob), None, None,
            0x1, ctypes.byref(destination),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source), ctypes.byref(returned_description), ctypes.byref(entropy_blob), None, None,
            0x1, ctypes.byref(destination),
        )
    _ = source_buffer, entropy_buffer
    if not ok:
        raise SecretStoreError(f"DPAPI a échoué avec le code Windows {ctypes.get_last_error()}.")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree(destination.pbData)
        if returned_description:
            kernel32.LocalFree(returned_description)


def _purpose_context(purpose: str) -> tuple[bytes, str]:
    if not _KEY.fullmatch(purpose):
        raise SecretStoreError("Contexte DPAPI invalide.")
    entropy = hashlib.sha256(
        b"marvin-dpapi-purpose-v1\0" + purpose.encode("ascii")
    ).digest()
    return entropy, f"Marvin {purpose}"


def protect_bytes(value: bytes, *, purpose: str) -> bytes:
    """Protège des octets pour l'utilisateur Windows courant et un usage précis."""
    if not isinstance(value, bytes) or not value or len(value) > 65_536:
        raise SecretStoreError("Charge binaire DPAPI invalide.")
    entropy, description = _purpose_context(purpose)
    return _crypt_with_context(
        value,
        protect=True,
        entropy=entropy,
        description=description,
    )


def unprotect_bytes(value: bytes, *, purpose: str) -> bytes:
    """Déprotège des octets uniquement dans le même contexte DPAPI."""
    if not isinstance(value, bytes) or not value or len(value) > 131_072:
        raise SecretStoreError("Charge binaire DPAPI invalide.")
    entropy, description = _purpose_context(purpose)
    return _crypt_with_context(
        value,
        protect=False,
        entropy=entropy,
        description=description,
    )


@contextmanager
def _interprocess_lock(timeout_seconds: float = 5.0):
    lock_path = PATH.with_suffix(PATH.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise SecretStoreError("Le verrou du coffre DPAPI est indisponible.")
                time.sleep(0.02)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_unlocked() -> dict[str, str]:
    if not PATH.exists():
        return {}
    try:
        value = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SecretStoreError("Le coffre DPAPI est illisible ou corrompu.") from exc
    if not isinstance(value, dict):
        raise SecretStoreError("Le coffre DPAPI possède un format invalide.")
    rows: dict[str, str] = {}
    for key, item in value.items():
        if not _KEY.fullmatch(str(key)) or not isinstance(item, str):
            raise SecretStoreError("Le coffre DPAPI contient une entrée invalide.")
        rows[str(key)] = item
    return rows


def _write_unlocked(value: dict[str, str]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PATH.with_name(f".{PATH.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, PATH)
    finally:
        temporary.unlink(missing_ok=True)


def set_secret(key: str, value: str) -> None:
    if not _KEY.fullmatch(key):
        raise SecretStoreError("Nom de secret invalide.")
    if not value or len(value) > 16_384:
        raise SecretStoreError("Valeur de secret vide ou trop longue.")
    encrypted = base64.b64encode(_crypt(value.encode("utf-8"), protect=True)).decode("ascii")
    with _LOCK, _interprocess_lock():
        rows = _load_unlocked()
        rows[key] = encrypted
        _write_unlocked(rows)


def get_secret(key: str) -> str | None:
    if not _KEY.fullmatch(key):
        raise SecretStoreError("Nom de secret invalide.")
    with _LOCK, _interprocess_lock():
        encoded = _load_unlocked().get(key)
    if not encoded:
        return None
    try:
        return _crypt(base64.b64decode(encoded, validate=True), protect=False).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise SecretStoreError("Secret DPAPI illisible pour ce compte Windows.") from exc


def has_secret(key: str) -> bool:
    if not _KEY.fullmatch(key):
        raise SecretStoreError("Nom de secret invalide.")
    with _LOCK, _interprocess_lock():
        return key in _load_unlocked()


def delete_secret(key: str) -> None:
    if not _KEY.fullmatch(key):
        raise SecretStoreError("Nom de secret invalide.")
    with _LOCK, _interprocess_lock():
        rows = _load_unlocked()
        rows.pop(key, None)
        _write_unlocked(rows)
