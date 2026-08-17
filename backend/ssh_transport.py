"""Transport SSH Paramiko partagé par l'API et les outils Marvin."""

from __future__ import annotations

import io
import os
import threading
from pathlib import Path
from typing import Any

import paramiko

from config import DATA_DIR


KNOWN_HOSTS_PATH = Path(DATA_DIR) / "ssh_known_hosts"
_HOST_KEY_LOCK = threading.RLock()


class TrustOnFirstUsePolicy(paramiko.MissingHostKeyPolicy):
    """Épingle atomiquement la première clé vue; tout changement ultérieur est refusé.

    La première connexion reste une confiance au premier usage (TOFU), pas une preuve PKI.
    L'empreinte doit être vérifiée hors bande pour une cible à forte sensibilité.
    """

    def missing_host_key(self, client, hostname, key):
        with _HOST_KEY_LOCK:
            KNOWN_HOSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            host_keys = paramiko.HostKeys()
            if KNOWN_HOSTS_PATH.exists():
                host_keys.load(str(KNOWN_HOSTS_PATH))
            existing = host_keys.lookup(hostname) or {}
            known = existing.get(key.get_name())
            if known is not None and known != key:
                raise paramiko.BadHostKeyException(hostname, key, known)
            host_keys.add(hostname, key.get_name(), key)
            temporary = KNOWN_HOSTS_PATH.with_suffix(".tmp")
            host_keys.save(str(temporary))
            os.replace(temporary, KNOWN_HOSTS_PATH)
            client.get_host_keys().add(hostname, key.get_name(), key)


def load_private_key(key_text: str, passphrase: str | None = None):
    """Charge une clé privée Ed25519, ECDSA, RSA ou DSS."""
    last_error: Exception | None = None
    key_classes = (
        getattr(paramiko, "Ed25519Key", None),
        getattr(paramiko, "ECDSAKey", None),
        paramiko.RSAKey,
        getattr(paramiko, "DSSKey", None),
    )
    for key_class in key_classes:
        if key_class is None:
            continue
        try:
            return key_class.from_private_key(
                io.StringIO(key_text), password=passphrase or None
            )
        except Exception as exc:
            last_error = exc
    raise ValueError(
        "Format de clé privée non reconnu (RSA/Ed25519/ECDSA/DSS). "
        f"{last_error}"
    )


def connect(connection: dict[str, Any], timeout: int = 30):
    """Ouvre une connexion SSH avec les paramètres historiques de Marvin."""
    client = paramiko.SSHClient()
    if KNOWN_HOSTS_PATH.exists():
        client.load_host_keys(str(KNOWN_HOSTS_PATH))
    client.set_missing_host_key_policy(TrustOnFirstUsePolicy())
    kwargs: dict[str, Any] = {
        "hostname": connection["host"],
        "port": int(connection.get("port", 22) or 22),
        "username": connection["username"],
        "timeout": timeout,
        "banner_timeout": timeout,
        "auth_timeout": timeout,
    }
    private_key = (connection.get("private_key") or "").strip()
    if private_key:
        kwargs["pkey"] = load_private_key(
            private_key, connection.get("key_passphrase")
        )
    elif connection.get("password"):
        kwargs["password"] = connection["password"]
    client.connect(**kwargs)
    return client
