"""Régressions du transport SSH partagé par API et outils."""

from __future__ import annotations

import sys
import tempfile
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
    with tempfile.TemporaryDirectory() as directory, (
        patch.object(ssh_transport, "KNOWN_HOSTS_PATH", Path(directory) / "known_hosts")
    ), patch.object(ssh_transport.paramiko, "SSHClient", return_value=client):
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
    policy = client.set_missing_host_key_policy.call_args.args[0]
    assert isinstance(policy, ssh_transport.TrustOnFirstUsePolicy)

    with tempfile.TemporaryDirectory() as directory, patch.object(
        ssh_transport, "KNOWN_HOSTS_PATH", Path(directory) / "known_hosts"
    ):
        first_key = ssh_transport.paramiko.RSAKey.generate(1024)
        changed_key = ssh_transport.paramiko.RSAKey.generate(1024)
        policy_client = MagicMock()
        policy_client.get_host_keys.return_value = ssh_transport.paramiko.HostKeys()
        policy.missing_host_key(policy_client, "server.example", first_key)
        assert ssh_transport.KNOWN_HOSTS_PATH.exists()
        pinned = ssh_transport.paramiko.HostKeys(str(ssh_transport.KNOWN_HOSTS_PATH))
        assert pinned.lookup("server.example")[first_key.get_name()] == first_key
        try:
            policy.missing_host_key(policy_client, "server.example", changed_key)
        except ssh_transport.paramiko.BadHostKeyException:
            pass
        else:
            raise AssertionError("Une clé SSH changée doit être refusée.")

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
