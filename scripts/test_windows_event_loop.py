"""Contrat du runtime asyncio résilient utilisé par Uvicorn sous Windows."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import server_runtime
import windows_event_loop


def main() -> int:
    assert windows_event_loop.RETRYABLE_ACCEPT_WINERRORS == frozenset({64})
    assert 0 < windows_event_loop.ACCEPT_RETRY_DELAY_SECONDS <= 1
    if sys.platform == "win32":
        loop = server_runtime.loop_factory()
        try:
            assert isinstance(loop, windows_event_loop.ResilientProactorEventLoop)
            assert isinstance(loop, asyncio.ProactorEventLoop)
        finally:
            loop.close()
    source = Path(windows_event_loop.__file__).read_text(encoding="utf-8")
    assert "call_later(ACCEPT_RETRY_DELAY_SECONDS, accept_next)" in source
    assert "create_subprocess_exec" not in source
    print("Windows Event Loop OK - Proactor conservé et WinError 64 réarmé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
