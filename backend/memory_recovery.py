"""Restauration coordonnée de SQLite et de ses projections mémoire."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Awaitable


Restore = Callable[[str], dict[str, Any]]
Initialize = Callable[[], None]
Repair = Callable[..., Awaitable[dict[str, Any]]]
EventLogger = Callable[[str, dict[str, Any]], None]


def _log_event(event: str, attributes: dict[str, Any]) -> None:
    try:
        import audit

        audit.log_action(
            event,
            result={
                "success": bool(attributes.get("success")),
                "compensated": bool(attributes.get("compensated")),
                "memory_actions": int(attributes.get("memory_actions") or 0),
                "error": attributes.get("error_code"),
            },
            source="runtime",
        )
    except Exception:
        pass


async def restore_and_reconcile(
    filename: str,
    *,
    restore: Restore,
    initialize: Initialize,
    repair: Repair,
    event_logger: EventLogger = _log_event,
) -> dict[str, Any]:
    """Restaure l'autorité puis reconstruit Mesh/Qdrant, avec compensation."""
    restored = await asyncio.to_thread(restore, filename)
    if not restored.get("success"):
        event_logger("memory_restore_reconcile", {
            "success": False,
            "error_code": restored.get("error_code"),
        })
        return restored
    pre_restore = str(restored.get("pre_restore_filename") or "")
    try:
        await asyncio.to_thread(initialize)
        reconciliation = await repair(dry_run=False)
        if not reconciliation.get("success"):
            raise RuntimeError("memory_reconciliation_failed")
        result = {
            **restored,
            "memory_reconciled": True,
            "memory_actions": len(reconciliation.get("actions") or []),
        }
        event_logger("memory_restore_reconcile", {
            "success": True,
            "memory_actions": result["memory_actions"],
        })
        return result
    except Exception as exc:
        compensated = False
        compensation_error_type = None
        if pre_restore:
            try:
                rollback = await asyncio.to_thread(restore, pre_restore)
                if not rollback.get("success"):
                    raise RuntimeError("database_compensation_failed")
                await asyncio.to_thread(initialize)
                rollback_reconciliation = await repair(dry_run=False)
                if not rollback_reconciliation.get("success"):
                    raise RuntimeError("projection_compensation_failed")
                compensated = True
            except Exception as rollback_exc:
                compensation_error_type = type(rollback_exc).__name__
        result = {
            "success": False,
            "error": "La restauration globale de la mémoire a échoué.",
            "error_code": "memory_restore_failed",
            "exception_type": type(exc).__name__,
            "compensated": compensated,
            "memory_reconciled": False,
        }
        if compensation_error_type:
            result["compensation_error_type"] = compensation_error_type
        event_logger("memory_restore_reconcile", {
            "success": False,
            "compensated": compensated,
            "error_code": result["error_code"],
        })
        return result
