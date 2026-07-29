"""Point d'entrée Uvicorn avec boucle Windows résiliente."""
from __future__ import annotations

import asyncio
import sys

import uvicorn

from windows_event_loop import ResilientProactorEventLoop


def loop_factory():
    if sys.platform == "win32":
        return ResilientProactorEventLoop()
    return asyncio.new_event_loop()


def main() -> int:
    config = uvicorn.Config(
        "main:app",
        host="127.0.0.1",
        port=8005,
        reload=False,
        access_log=True,
    )
    server = uvicorn.Server(config)
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(server.serve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
