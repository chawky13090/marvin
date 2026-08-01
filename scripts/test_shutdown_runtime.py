"""Régression : aucun composant ne peut bloquer la fermeture FastAPI."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import shutdown_runtime


async def _checks() -> None:
    called: list[str] = []

    async def clean() -> None:
        called.append("clean")

    assert await shutdown_runtime.run("clean", clean, timeout=0.1) is True
    assert called == ["clean"]

    async def blocking_native_call() -> None:
        await asyncio.to_thread(time.sleep, 0.25)

    started = time.monotonic()
    with patch.object(shutdown_runtime.bug_log, "log_bug") as log_bug:
        assert await shutdown_runtime.run(
            "blocked", blocking_native_call, timeout=0.02
        ) is False
        log_bug.assert_called_once()
    assert time.monotonic() - started < 0.15


def _check_server_drain_guard() -> None:
    source = (ROOT / "backend" / "server_runtime.py").read_text(encoding="utf-8-sig")
    assert "POST_SHUTDOWN_DRAIN_SECONDS" in source
    assert "threading.Timer" in source
    assert source.index("runner.run(_serve(server))") < source.index("drain_guard.start()")
    assert "os._exit(0)" in source


if __name__ == "__main__":
    asyncio.run(_checks())
    _check_server_drain_guard()
    print("Shutdown Runtime OK - composants bornés et drain post-lifespan contrôlé.")
