"""Vérifie que la suppression des copies mortes SSH préserve toutes les routes actives."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    import main
    from api.ssh import SSHCommandRequest, SSHConnectionCreate, _ssh_error

    audit_rows = []
    with patch.dict(
        sys.modules,
        {"audit": SimpleNamespace(
            log_action=lambda action, **kwargs: audit_rows.append((action, kwargs))
        )},
    ):
        message = _ssh_error(
            RuntimeError("private host and C:\\private\\key.pem")
        )
    assert message == "Opération SSH impossible."
    assert "private" not in repr(audit_rows)
    assert audit_rows[0][1]["result"]["error_type"] == "RuntimeError"

    invalid_payloads = (
        (SSHConnectionCreate, {
            "name": "test", "host": "host", "port": 0,
            "username": "user", "password": "x",
        }),
        (SSHConnectionCreate, {
            "name": "test", "host": "host", "username": "user",
            "private_key": "x" * 12_001,
        }),
        (SSHCommandRequest, {
            "connection_id": "id", "command": "true", "timeout": 301,
        }),
    )
    for model, payload in invalid_payloads:
        try:
            model(**payload)
        except ValidationError:
            pass
        else:
            raise AssertionError("La charge SSH hors limites doit être refusée.")

    expected = {
        ("/api/ssh", "GET"),
        ("/api/ssh", "POST"),
        ("/api/ssh/{sid}", "PUT"),
        ("/api/ssh/{sid}", "DELETE"),
        ("/api/ssh/test", "POST"),
        ("/api/ssh/exec", "POST"),
        ("/api/ssh/exec/stream", "GET"),
        ("/api/ssh/{sid}/browse", "GET"),
        ("/api/ssh/{sid}/info", "GET"),
        ("/api/ssh/{sid}/download", "GET"),
        ("/api/ssh/{sid}/upload", "POST"),
    }
    observed: set[tuple[str, str]] = set()
    websocket = False
    for route in main.app.routes:
        path = getattr(route, "path", "")
        endpoint = getattr(route, "endpoint", None)
        if not path.startswith("/api/ssh") or endpoint is None:
            continue
        assert endpoint.__module__ == "api.ssh", (path, endpoint.__module__)
        methods = getattr(route, "methods", None)
        if methods:
            observed.update((path, method) for method in methods if method != "HEAD")
        elif path == "/api/ssh/{sid}/shell":
            websocket = True
    assert expected <= observed, sorted(expected - observed)
    assert websocket

    source = inspect.getsource(main)
    assert "Migré vers api/ssh.py" not in source
    assert "class SSHConnectionCreate" not in source
    assert "async def ssh_shell_ws" not in source
    print("SSH Router Boundary OK - 11 contrats HTTP, WebSocket et module unique api.ssh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
