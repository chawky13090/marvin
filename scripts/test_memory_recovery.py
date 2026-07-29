"""Contrats de restauration autoritative SQLite vers Mesh et Qdrant."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import memory_recovery


def test_success() -> None:
    calls: list[str] = []

    def restore(filename: str):
        calls.append(f"restore:{filename}")
        return {
            "success": True,
            "pre_restore_filename": "before.mrvbak",
        }

    def initialize():
        calls.append("initialize")

    async def repair(*, dry_run: bool):
        assert dry_run is False
        calls.append("repair")
        return {"success": True, "actions": [{}, {}]}

    result = asyncio.run(memory_recovery.restore_and_reconcile(
        "target.mrvbak",
        restore=restore,
        initialize=initialize,
        repair=repair,
        event_logger=lambda event, attrs: calls.append(
            f"log:{event}:{attrs['success']}"
        ),
    ))
    assert result["success"] is True
    assert result["memory_reconciled"] is True
    assert result["memory_actions"] == 2
    assert calls == [
        "restore:target.mrvbak",
        "initialize",
        "repair",
        "log:memory_restore_reconcile:True",
    ]


def test_projection_failure_compensates_database_and_projections() -> None:
    calls: list[str] = []
    repairs = iter(({"success": False}, {"success": True}))

    def restore(filename: str):
        calls.append(f"restore:{filename}")
        return {
            "success": True,
            "pre_restore_filename": "before.mrvbak",
        }

    def initialize():
        calls.append("initialize")

    async def repair(*, dry_run: bool):
        assert dry_run is False
        calls.append("repair")
        return next(repairs)

    result = asyncio.run(memory_recovery.restore_and_reconcile(
        "target.mrvbak",
        restore=restore,
        initialize=initialize,
        repair=repair,
        event_logger=lambda event, attrs: calls.append(
            f"log:{event}:{attrs['success']}:{attrs.get('compensated')}"
        ),
    ))
    assert result["success"] is False
    assert result["compensated"] is True
    assert calls == [
        "restore:target.mrvbak",
        "initialize",
        "repair",
        "restore:before.mrvbak",
        "initialize",
        "repair",
        "log:memory_restore_reconcile:False:True",
    ]


def test_database_failure_does_not_touch_projections() -> None:
    initialized = False

    def restore(_filename: str):
        return {"success": False, "error_code": "invalid_backup"}

    def initialize():
        nonlocal initialized
        initialized = True

    async def repair(*, dry_run: bool):
        raise AssertionError("La réparation ne doit pas être appelée.")

    result = asyncio.run(memory_recovery.restore_and_reconcile(
        "bad.mrvbak",
        restore=restore,
        initialize=initialize,
        repair=repair,
        event_logger=lambda _event, _attrs: None,
    ))
    assert result["success"] is False
    assert initialized is False


def main() -> int:
    test_success()
    test_projection_failure_compensates_database_and_projections()
    test_database_failure_does_not_touch_projections()
    print("Memory Recovery OK - reconstruction, panne et compensation globale.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
