"""Point d'entrée Uvicorn avec boucle Windows résiliente."""
from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

import uvicorn

from windows_event_loop import ResilientProactorEventLoop


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHUTDOWN_REQUEST = PROJECT_ROOT / "runtime" / "lifecycle" / "backend.shutdown"


def loop_factory():
    if sys.platform == "win32":
        return ResilientProactorEventLoop()
    return asyncio.new_event_loop()


async def _watch_shutdown(server: uvicorn.Server) -> None:
    """Transforme la demande locale en arrêt Uvicorn coopératif."""
    while not server.should_exit:
        if SHUTDOWN_REQUEST.exists():
            server.should_exit = True
            return
        await asyncio.sleep(0.25)


async def _serve(server: uvicorn.Server) -> None:
    watcher = asyncio.create_task(_watch_shutdown(server), name="marvin-shutdown-watch")
    try:
        await server.serve()
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
        SHUTDOWN_REQUEST.unlink(missing_ok=True)


def main() -> int:
    SHUTDOWN_REQUEST.parent.mkdir(parents=True, exist_ok=True)
    # Une requête laissée par une extinction Windows ne doit jamais arrêter le
    # prochain démarrage. Seul stop-marvin.ps1 la recrée après le lancement.
    SHUTDOWN_REQUEST.unlink(missing_ok=True)
    config = uvicorn.Config(
        "main:app",
        host="127.0.0.1",
        port=8005,
        reload=False,
        access_log=True,
    )
    server = uvicorn.Server(config)
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(_serve(server))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
