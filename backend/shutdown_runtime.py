"""Arrêt borné des composants asynchrones du backend Marvin."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import bug_log


LOGGER = logging.getLogger("marvin.shutdown")
DEFAULT_COMPONENT_TIMEOUT_SECONDS = 5.0


async def run(
    name: str,
    operation: Callable[[], Awaitable[object]],
    *,
    timeout: float = DEFAULT_COMPONENT_TIMEOUT_SECONDS,
) -> bool:
    """Exécute une fermeture sans laisser un composant bloquer tout Uvicorn.

    ``asyncio.wait`` est volontairement utilisé plutôt que ``wait_for`` : ce dernier
    attend que la coroutine accepte son annulation et peut donc rester bloqué sur un
    appel natif ou un thread récalcitrant.
    """
    task = asyncio.create_task(operation(), name=f"shutdown:{name}")
    done, _ = await asyncio.wait({task}, timeout=max(0.1, float(timeout)))
    if task not in done:
        task.cancel()
        LOGGER.error("Arrêt de %s expiré après %.1f s", name, timeout)
        bug_log.log_bug(
            "shutdown_component_timeout",
            "TimeoutError",
            context={"component": name, "timeout_seconds": float(timeout)},
        )
        return False
    try:
        task.result()
    except asyncio.CancelledError:
        return True
    except Exception as exc:
        LOGGER.error("Arrêt de %s en erreur: %s", name, type(exc).__name__)
        bug_log.log_bug(
            "shutdown_component_failure",
            type(exc).__name__,
            context={"component": name, "exception_type": type(exc).__name__},
        )
        return False
    return True
