"""Régressions du domaine SSH et de sa façade tools.py."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from tool_domains import ssh as ssh_domain


class _Channel:
    def recv_exit_status(self):
        return 0


class _Stream:
    channel = _Channel()

    def __init__(self, content: bytes):
        self.content = content

    def read(self):
        return self.content


async def _run() -> None:
    connection = {
        "id": "s1", "name": "Debian", "host": "10.0.0.2", "port": 22,
        "username": "marvin", "password": "secret", "private_key": "", "last_used": None,
    }
    with patch.object(ssh_domain.db, "list_ssh_connections", return_value=[connection]):
        listed = await ssh_domain.list_connections({})
    assert listed["count"] == 1
    assert "password" not in listed["connections"][0]
    assert listed["connections"][0]["has_password"] is True

    refused = await ssh_domain.save_connection({
        "name": "Debian", "host": "10.0.0.2", "username": "marvin", "password": "secret"
    })
    assert refused["credentials_ui_required"] is True
    _, error = ssh_domain.resolve_target({
        "host": "10.0.0.2", "username": "marvin", "password": "x", "port": "invalid"
    })
    assert error == "Port SSH invalide."

    with (
        patch.object(ssh_domain.db, "get_ssh_connection", return_value=connection),
        patch.object(ssh_domain.security, "guard_result", return_value=None),
    ):
        confirmation = await ssh_domain.execute({
            "connection_id": "s1", "command": "uname -a"
        })
    assert confirmation["requiresConfirmation"] is True

    client = MagicMock()
    client.exec_command.return_value = (None, _Stream(b"Linux\n"), _Stream(b""))
    with (
        patch.object(ssh_domain.db, "get_ssh_connection", return_value=connection),
        patch.object(ssh_domain.db, "touch_ssh_connection") as touch,
        patch.object(ssh_domain.security, "guard_result", return_value=None),
        patch.object(ssh_domain.ssh_transport, "connect", return_value=client),
    ):
        result = await ssh_domain.execute({
            "connection_id": "s1", "command": "uname -a", "confirmed": True
        })
    assert result["success"] is True and result["stdout"] == "Linux\n"
    touch.assert_called_once_with("s1")
    client.close.assert_called_once_with()


def main() -> int:
    asyncio.run(_run())
    import tools

    expected = {
        "ssh_list": ssh_domain.list_connections,
        "ssh_connection_save": ssh_domain.save_connection,
        "ssh_exec": ssh_domain.execute,
        "ssh_exec_multi": ssh_domain.execute_multi,
        "ssh_write_and_run": ssh_domain.write_and_run,
        "ssh_upload": ssh_domain.upload,
        "ssh_download": ssh_domain.download,
        "ssh_list_dir": ssh_domain.list_dir,
        "ssh_server_info": ssh_domain.server_info,
    }
    for name, function in expected.items():
        assert tools.TOOLS_REGISTRY[name] is function, name
        assert any(spec["function"]["name"] == name for spec in tools.TOOLS_SPEC), name
    assert len(tools.TOOLS_REGISTRY) == len(tools.TOOLS_SPEC)
    api_source = (BACKEND / "api" / "ssh.py").read_text(encoding="utf-8")
    assert "import tools" not in api_source and "tool_module" not in api_source
    print("Tool Domain SSH OK - secrets, garde, exécution, API et façade synchronisée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
