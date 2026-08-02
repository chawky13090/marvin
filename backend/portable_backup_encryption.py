"""Chiffrement portable AES-256-GCM avec dérivation scrypt d'une phrase secrète."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


MAGIC = b"MRVPRT01"
PURPOSE = "marvin-portable-backup-v1"
MAX_HEADER = 65_536
MAX_PASSPHRASE_CHARS = 1_024
MIN_PASSPHRASE_CHARS = 12
CHUNK_SIZE = 1024 * 1024
TAG_SIZE = 16
SCRYPT_N = 2**17
SCRYPT_R = 8
SCRYPT_P = 1


class PortableEncryptionError(ValueError):
    pass


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: object, *, exact: int) -> bytes:
    if not isinstance(value, str) or len(value) > exact * 2:
        raise PortableEncryptionError("Métadonnée chiffrée invalide.")
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise PortableEncryptionError("Métadonnée chiffrée invalide.") from exc
    if len(decoded) != exact:
        raise PortableEncryptionError("Métadonnée chiffrée invalide.")
    return decoded


def _passphrase_bytes(passphrase: str, *, creating: bool) -> bytes:
    if not isinstance(passphrase, str) or len(passphrase) > MAX_PASSPHRASE_CHARS:
        raise PortableEncryptionError("Phrase secrète invalide.")
    if creating and len(passphrase) < MIN_PASSPHRASE_CHARS:
        raise PortableEncryptionError(
            f"La phrase secrète doit contenir au moins {MIN_PASSPHRASE_CHARS} caractères."
        )
    encoded = passphrase.encode("utf-8")
    if not encoded:
        raise PortableEncryptionError("Phrase secrète invalide.")
    return encoded


def _derive(passphrase: bytes, salt: bytes, *, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase)


def encrypt_file(source: Path, destination: Path, *, passphrase: str) -> dict[str, object]:
    secret = _passphrase_bytes(passphrase, creating=True)
    salt, nonce = os.urandom(16), os.urandom(12)
    key = _derive(secret, salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    size = source.stat().st_size
    header = {
        "schema": 1,
        "cipher": "AES-256-GCM",
        "kdf": "scrypt",
        "n": SCRYPT_N,
        "r": SCRYPT_R,
        "p": SCRYPT_P,
        "salt": _encode(salt),
        "nonce": _encode(nonce),
        "plaintext_size": size,
        "purpose": PURPOSE,
        "portable": True,
    }
    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(header_bytes) > MAX_HEADER:
        raise PortableEncryptionError("En-tête de sauvegarde trop grand.")
    digest = hashlib.sha256()
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header_bytes)
    try:
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
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return {"sha256": digest.hexdigest(), "plaintext_size": size}


def decrypt_file(source: Path, destination: Path, *, passphrase: str) -> dict[str, object]:
    secret = _passphrase_bytes(passphrase, creating=False)
    total = source.stat().st_size
    try:
        with source.open("rb") as reader:
            if reader.read(len(MAGIC)) != MAGIC:
                raise PortableEncryptionError("Format de sauvegarde portable inconnu.")
            raw_length = reader.read(4)
            if len(raw_length) != 4:
                raise PortableEncryptionError("En-tête de sauvegarde tronqué.")
            header_length = struct.unpack(">I", raw_length)[0]
            if not 1 <= header_length <= MAX_HEADER:
                raise PortableEncryptionError("En-tête de sauvegarde invalide.")
            header_bytes = reader.read(header_length)
            try:
                header = json.loads(header_bytes)
            except (UnicodeDecodeError, ValueError) as exc:
                raise PortableEncryptionError("En-tête de sauvegarde invalide.") from exc
            if (
                header.get("schema") != 1
                or header.get("cipher") != "AES-256-GCM"
                or header.get("kdf") != "scrypt"
                or header.get("purpose") != PURPOSE
                or header.get("portable") is not True
            ):
                raise PortableEncryptionError("Version de sauvegarde non prise en charge.")
            n, r, p = header.get("n"), header.get("r"), header.get("p")
            if (n, r, p) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
                raise PortableEncryptionError("Paramètres de dérivation non pris en charge.")
            salt = _decode(header.get("salt"), exact=16)
            nonce = _decode(header.get("nonce"), exact=12)
            key = _derive(secret, salt, n=n, r=r, p=p)
            ciphertext_length = total - len(MAGIC) - 4 - header_length - TAG_SIZE
            if ciphertext_length < 1:
                raise PortableEncryptionError("Sauvegarde chiffrée tronquée.")
            reader.seek(total - TAG_SIZE)
            tag = reader.read(TAG_SIZE)
            reader.seek(len(MAGIC) + 4 + header_length)
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(header_bytes)
            digest, remaining = hashlib.sha256(), ciphertext_length
            with destination.open("xb") as writer:
                while remaining:
                    chunk = reader.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise PortableEncryptionError("Sauvegarde chiffrée tronquée.")
                    remaining -= len(chunk)
                    plain = decryptor.update(chunk)
                    digest.update(plain)
                    writer.write(plain)
                final = decryptor.finalize()
                digest.update(final)
                writer.write(final)
                writer.flush()
                os.fsync(writer.fileno())
    except InvalidTag as exc:
        destination.unlink(missing_ok=True)
        raise PortableEncryptionError(
            "Phrase secrète incorrecte ou sauvegarde altérée."
        ) from exc
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    expected_size = header.get("plaintext_size")
    if not isinstance(expected_size, int) or expected_size != destination.stat().st_size:
        destination.unlink(missing_ok=True)
        raise PortableEncryptionError("Taille déchiffrée incohérente.")
    return {"sha256": digest.hexdigest(), "plaintext_size": expected_size}
