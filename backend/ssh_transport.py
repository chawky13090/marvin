"""Transport SSH Paramiko partagé par l'API et les outils Marvin."""

from __future__ import annotations

import io
from typing import Any

import paramiko


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
    # Compatibilité historique : l'UI n'expose pas encore la gestion known_hosts.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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
