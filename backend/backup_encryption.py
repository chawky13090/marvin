"""Format versionné de sauvegarde AES-256-GCM, clé de données protégée par DPAPI."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
from pathlib import Path
from typing import Callable

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from dpapi_secret_store import protect_bytes, unprotect_bytes


MAGIC = b"MRVBAK01"
PURPOSE = "database-backup-v1"
MAX_HEADER = 65_536
CHUNK_SIZE = 1024 * 1024
TAG_SIZE = 16
Wrap = Callable[[bytes], bytes]


class BackupEncryptionError(ValueError):
    pass


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: object, *, maximum: int) -> bytes:
    if not isinstance(value, str) or len(value) > maximum * 2:
        raise BackupEncryptionError("Métadonnée chiffrée invalide.")
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise BackupEncryptionError("Métadonnée chiffrée invalide.") from exc
    if not decoded or len(decoded) > maximum:
        raise BackupEncryptionError("Métadonnée chiffrée invalide.")
    return decoded


def encrypt_file(
    source: Path,
    destination: Path,
    *,
    wrap: Wrap | None = None,
) -> dict[str, object]:
    wrap = wrap or (lambda key: protect_bytes(key, purpose=PURPOSE))
    key, nonce = os.urandom(32), os.urandom(12)
    digest = hashlib.sha256()
    size = source.stat().st_size
    header = {
        "schema": 1,
        "cipher": "AES-256-GCM",
        "key_scope": "dpapi-current-user",
        "portable": False,
        "nonce": _encode(nonce),
        "wrapped_key": _encode(wrap(key)),
        "plaintext_size": size,
    }
    header_bytes = json.dumps(
        header, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(header_bytes) > MAX_HEADER:
        raise BackupEncryptionError("En-tête de sauvegarde trop grand.")
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header_bytes)
    with source.open("rb") as reader, destination.open("xb") as writer:
        writer.write(MAGIC)
        writer.write(struct.pack(">I", len(header_bytes)))
        writer.write(header_bytes)
        for chunk in iter(lambda: reader.read(CHUNK_SIZE), b""):
            digest.update(chunk)
            writer.write(encryptor.update(chunk))
        writer.write(encryptor.finalize())
        writer.write(encryptor.tag)
        writer.flush()
        os.fsync(writer.fileno())
    return {"sha256": digest.hexdigest(), "plaintext_size": size}


def decrypt_file(
    source: Path,
    destination: Path,
    *,
    unwrap: Wrap | None = None,
) -> dict[str, object]:
    unwrap = unwrap or (lambda value: unprotect_bytes(value, purpose=PURPOSE))
    total = source.stat().st_size
    with source.open("rb") as reader:
        if reader.read(len(MAGIC)) != MAGIC:
            raise BackupEncryptionError("Format de sauvegarde inconnu.")
        raw_length = reader.read(4)
        if len(raw_length) != 4:
            raise BackupEncryptionError("En-tête de sauvegarde tronqué.")
        header_length = struct.unpack(">I", raw_length)[0]
        if not 1 <= header_length <= MAX_HEADER:
            raise BackupEncryptionError("En-tête de sauvegarde invalide.")
        header_bytes = reader.read(header_length)
        try:
            header = json.loads(header_bytes)
        except (UnicodeDecodeError, ValueError) as exc:
            raise BackupEncryptionError("En-tête de sauvegarde invalide.") from exc
        if header.get("schema") != 1 or header.get("cipher") != "AES-256-GCM":
            raise BackupEncryptionError("Version de sauvegarde non prise en charge.")
        nonce = _decode(header.get("nonce"), maximum=12)
        if len(nonce) != 12:
            raise BackupEncryptionError("Nonce de sauvegarde invalide.")
        key = unwrap(_decode(header.get("wrapped_key"), maximum=4096))
        if len(key) != 32:
            raise BackupEncryptionError("Clé de sauvegarde invalide.")
        ciphertext_length = total - len(MAGIC) - 4 - header_length - TAG_SIZE
        if ciphertext_length < 1:
            raise BackupEncryptionError("Sauvegarde chiffrée tronquée.")
        reader.seek(total - TAG_SIZE)
        tag = reader.read(TAG_SIZE)
        reader.seek(len(MAGIC) + 4 + header_length)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(header_bytes)
        digest, remaining = hashlib.sha256(), ciphertext_length
        try:
            with destination.open("xb") as writer:
                while remaining:
                    chunk = reader.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise BackupEncryptionError("Sauvegarde chiffrée tronquée.")
                    remaining -= len(chunk)
                    plain = decryptor.update(chunk)
                    digest.update(plain)
                    writer.write(plain)
                final = decryptor.finalize()
                digest.update(final)
                writer.write(final)
                writer.flush()
                os.fsync(writer.fileno())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    expected_size = header.get("plaintext_size")
    if not isinstance(expected_size, int) or expected_size != destination.stat().st_size:
        destination.unlink(missing_ok=True)
        raise BackupEncryptionError("Taille déchiffrée incohérente.")
    return {"sha256": digest.hexdigest(), "plaintext_size": expected_size}
