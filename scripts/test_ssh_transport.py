"""Régressions du transport SSH partagé par API et outils."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import ssh_transport


class _RejectedKey:
    @classmethod
    def from_private_key(cls, stream, password=None):
        raise ValueError("mauvais format")


class _AcceptedKey:
    @classmethod
    def from_private_key(cls, stream, password=None):
        assert stream.read() == "PRIVATE"
        assert password == "phrase"
        return "parsed-key"


def main() -> int:
    with (
        patch.object(ssh_transport.paramiko, "Ed25519Key", _RejectedKey),
        patch.object(ssh_transport.paramiko, "ECDSAKey", _AcceptedKey),
    ):
        assert ssh_transport.load_private_key("PRIVATE", "phrase") == "parsed-key"

    client = MagicMock()
    with patch.object(ssh_transport.paramiko, "SSHClient", return_value=client):
        result = ssh_transport.connect(
            {
                "host": "server.example",
                "port": 2222,
                "username": "marvin",
                "password": "secret",
            },
            timeout=9,
        )
    assert result is client
    kwargs = client.connect.call_args.kwargs
    assert kwargs == {
        "hostname": "server.example",
        "port": 2222,
        "username": "marvin",
        "timeout": 9,
        "banner_timeout": 9,
        "auth_timeout": 9,
        "password": "secret",
    }
    client.set_missing_host_key_policy.assert_called_once()

    import tools
    from api import ssh as ssh_api

    assert tools._ssh_connect is ssh_transport.connect
    assert tools._ssh_load_key is ssh_transport.load_private_key
    source = (BACKEND / "api" / "ssh.py").read_text(encoding="utf-8")
    assert "tool_module._ssh_connect" not in source
    assert "ssh_transport.connect" in source
    assert ssh_api.ssh_transport is ssh_transport
    print("SSH Transport OK - clés, mot de passe, timeouts et dépendance API partagée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
