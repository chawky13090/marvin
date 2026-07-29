"""Protection DPAPI versionnée du contenu des souvenirs Marvin."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable

from dpapi_secret_store import protect_bytes, unprotect_bytes


PREFIX = "dpapi:v1:"
PURPOSE = "marvin-memory-content-v1"
MAX_PLAINTEXT_BYTES = 128_000
CHUNK_BYTES = 48_000
Protect = Callable[[bytes], bytes]
Unprotect = Callable[[bytes], bytes]


class MemoryCipherError(RuntimeError):
    pass


def is_protected(value: str) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def protect_text(
    value: str,
    *,
    protect: Protect | None = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryCipherError("Le contenu mémoire est vide.")
    raw = value.encode("utf-8")
    if len(raw) > MAX_PLAINTEXT_BYTES:
        raise MemoryCipherError("Le contenu mémoire dépasse la limite chiffrable.")
    protector = protect or (
        lambda chunk: protect_bytes(chunk, purpose=PURPOSE)
    )
    try:
        chunks = [
            base64.b64encode(protector(raw[offset : offset + CHUNK_BYTES])).decode("ascii")
            for offset in range(0, len(raw), CHUNK_BYTES)
        ]
        encoded = PREFIX + json.dumps(chunks, separators=(",", ":"))
        if protect is None and unprotect_text(encoded) != value:
            raise MemoryCipherError("La relecture DPAPI du souvenir a échoué.")
        return encoded
    except MemoryCipherError:
        raise
    except Exception as exc:
        raise MemoryCipherError("Le contenu mémoire n'a pas pu être protégé.") from exc


def unprotect_text(
    value: str,
    *,
    unprotect: Unprotect | None = None,
    allow_plaintext: bool = False,
) -> str:
    if not isinstance(value, str):
        raise MemoryCipherError("Le contenu mémoire possède un type invalide.")
    if not is_protected(value):
        if allow_plaintext:
            return value
        raise MemoryCipherError("Le contenu mémoire n'est pas protégé.")
    unprotector = unprotect or (
        lambda chunk: unprotect_bytes(chunk, purpose=PURPOSE)
    )
    try:
        payload = json.loads(value[len(PREFIX) :])
        if (
            not isinstance(payload, list)
            or not payload
            or len(payload) > 4
            or any(not isinstance(item, str) or len(item) > 100_000 for item in payload)
        ):
            raise MemoryCipherError("L'enveloppe mémoire est invalide.")
        raw = b"".join(
            unprotector(base64.b64decode(item, validate=True))
            for item in payload
        )
        if not raw or len(raw) > MAX_PLAINTEXT_BYTES:
            raise MemoryCipherError("La charge mémoire déchiffrée est invalide.")
        return raw.decode("utf-8")
    except MemoryCipherError:
        raise
    except Exception as exc:
        raise MemoryCipherError("Le contenu mémoire protégé est illisible.") from exc
