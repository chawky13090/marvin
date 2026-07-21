"""Regressions deterministes du cycle de vie des workers Marvin."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from runtime_supervisor import RuntimeSupervisor


async def _run() -> None:
    test_logger = logging.getLogger("marvin.runtime.test")
    test_logger.disabled = True
    supervisor = RuntimeSupervisor(logger=test_logger)
    started = 0
    release = asyncio.Event()

    async def worker() -> None:
        nonlocal started
        started += 1
        await release.wait()

    first = supervisor.start("same-worker", worker)
    second = supervisor.start("same-worker", worker)
    await asyncio.sleep(0)
    assert first is second
    assert started == 1
    assert supervisor.snapshot()["tasks"][0]["status"] == "running"

    release.set()
    await first
    await asyncio.sleep(0)
    assert supervisor.snapshot()["tasks"][0]["status"] == "completed"

    restarted = supervisor.start("same-worker", worker)
    await restarted
    await asyncio.sleep(0)
    restarted_state = supervisor.snapshot()["tasks"][0]
    assert restarted_state["starts"] == 2
    assert restarted_state["status"] == "completed"

    async def failing_worker() -> None:
        raise ValueError("failure captured")

    failed = supervisor.start("failing-worker", failing_worker)
    try:
        await failed
    except ValueError:
        pass
    else:
        raise AssertionError("Le worker de test devait echouer.")
    await asyncio.sleep(0)
    states = {item["name"]: item for item in supervisor.snapshot()["tasks"]}
    assert states["failing-worker"]["status"] == "failed"
    assert states["failing-worker"]["last_error"] == "ValueError: failure captured"

    cancelled = asyncio.Event()

    async def cancellable_worker() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    supervisor.start("cancellable-worker", cancellable_worker)
    await asyncio.sleep(0)
    assert await supervisor.shutdown(timeout=1.0) == []
    assert cancelled.is_set()
    assert supervisor.closed
    assert await supervisor.shutdown(timeout=1.0) == []
    try:
        supervisor.start("forbidden", worker)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Un superviseur ferme ne doit pas redemarrer de worker.")


def main() -> int:
    asyncio.run(_run())
    print("Runtime Supervisor OK - idempotence, erreurs, relance et arret cooperatif.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
