"""Supervision idempotente des taches asynchrones du processus Marvin.

Le superviseur ne connait aucun domaine metier. Il fournit uniquement un cycle de
vie commun aux workers FastAPI : demarrage nomme, absence de doublon, collecte des
erreurs et arret cooperatif. Les fonctions metier restent dans leurs modules.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


TaskFactory = Callable[[], Awaitable[Any]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _TaskRecord:
    name: str
    task: asyncio.Task[Any]
    starts: int
    started_at: str
    status: str = "running"
    finished_at: str | None = None
    last_error: str | None = None


class RuntimeSupervisor:
    """Possede et observe les taches de fond d'une instance FastAPI."""

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("marvin.runtime")
        self._records: dict[str, _TaskRecord] = {}
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def start(self, name: str, factory: TaskFactory) -> asyncio.Task[Any]:
        """Demarre une seule instance active du worker nomme."""
        normalized = name.strip()
        if not normalized:
            raise ValueError("Le nom d'un worker ne peut pas etre vide.")
        if self._closed:
            raise RuntimeError("Le superviseur est ferme.")

        previous = self._records.get(normalized)
        if previous is not None and not previous.task.done():
            return previous.task

        starts = 1 if previous is None else previous.starts + 1
        try:
            awaitable = factory()
        except Exception:
            self._logger.exception("Echec de creation du worker %s", normalized)
            raise

        task = asyncio.create_task(awaitable, name=f"marvin:{normalized}")
        record = _TaskRecord(
            name=normalized,
            task=task,
            starts=starts,
            started_at=_utc_now(),
        )
        self._records[normalized] = record
        task.add_done_callback(lambda completed, current=record: self._on_done(current, completed))
        return task

    def _on_done(self, record: _TaskRecord, task: asyncio.Task[Any]) -> None:
        record.finished_at = _utc_now()
        if task.cancelled():
            record.status = "cancelled"
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            record.status = "cancelled"
            return
        if error is None:
            record.status = "completed"
            return
        record.status = "failed"
        record.last_error = f"{type(error).__name__}: {error}"[:2000]
        self._logger.error(
            "Worker %s termine en erreur: %s",
            record.name,
            record.last_error,
            exc_info=(type(error), error, error.__traceback__),
        )

    async def stop(self, name: str, *, timeout: float = 10.0) -> bool:
        """Arrete un worker; l'absence du worker est deja un succes."""
        record = self._records.get(name)
        if record is None or record.task.done():
            return True
        record.task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(record.task), timeout=timeout)
        except asyncio.CancelledError:
            return True
        except asyncio.TimeoutError:
            self._logger.error("Le worker %s ne s'est pas arrete en %.1f s", name, timeout)
            return False
        except Exception:
            return True
        return True

    async def shutdown(self, *, timeout: float = 15.0) -> list[str]:
        """Annule tous les workers et retourne ceux qui ignorent encore l'arret."""
        self._closed = True
        running = [record.task for record in self._records.values() if not record.task.done()]
        if not running:
            return []
        for task in running:
            task.cancel()
        _, pending = await asyncio.wait(running, timeout=timeout)
        pending_names = sorted(task.get_name() for task in pending)
        if pending_names:
            self._logger.error(
                "Workers toujours actifs apres %.1f s: %s", timeout, ", ".join(pending_names)
            )
            for task in pending:
                task.cancel()
        return pending_names

    def snapshot(self) -> dict[str, Any]:
        tasks = []
        for name in sorted(self._records):
            record = self._records[name]
            status = record.status
            if not record.task.done():
                status = "stopping" if record.task.cancelling() else "running"
            tasks.append(
                {
                    "name": record.name,
                    "status": status,
                    "starts": record.starts,
                    "started_at": record.started_at,
                    "finished_at": record.finished_at,
                    "last_error": record.last_error,
                }
            )
        return {"closed": self._closed, "tasks": tasks}
