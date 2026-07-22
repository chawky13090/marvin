"""Vérifie que la suppression des copies mortes SSH préserve toutes les routes actives."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    import main

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
