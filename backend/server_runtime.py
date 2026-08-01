"""Point d'entrée Uvicorn avec boucle Windows résiliente."""
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import threading
from pathlib import Path

import uvicorn

from windows_event_loop import ResilientProactorEventLoop


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHUTDOWN_REQUEST = PROJECT_ROOT / "runtime" / "lifecycle" / "backend.shutdown"
POST_SHUTDOWN_DRAIN_SECONDS = 8.0


def _exit_after_clean_shutdown_timeout() -> None:
    """Termine uniquement après la fin confirmée du lifespan FastAPI.

    Python peut sinon attendre indéfiniment un thread d'exécuteur déjà détaché alors
    que les sockets, bases et clients de Marvin sont fermés. Ce repli ne peut jamais
    interrompre une requête : il n'est armé qu'après ``server.serve()``.
    """
    try:
        sys.stderr.write(
            "[Marvin] Drain des threads résiduels expiré après arrêt propre; "
            "fin bornée du processus.\n"
        )
        sys.stderr.flush()
        sys.stdout.flush()
    finally:
        os._exit(0)


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
    runner = asyncio.Runner(loop_factory=loop_factory)
    runner.run(_serve(server))
    drain_guard = threading.Timer(
        POST_SHUTDOWN_DRAIN_SECONDS,
        _exit_after_clean_shutdown_timeout,
    )
    drain_guard.daemon = True
    drain_guard.start()
    try:
        runner.close()
    finally:
        drain_guard.cancel()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
