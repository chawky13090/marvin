"""Regressions sans envoi reel des workers e-mail et agenda."""

from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import communication_workers


EXPECTED_ALIASES = {
    "_bg_scale": "background_scale",
    "_calendar_sync_worker": "calendar_sync_worker",
    "_email_automation_worker": "email_automation_worker",
    "_email_watch_worker": "email_watch_worker",
    "_event_reminder_worker": "event_reminder_worker",
}


class StopWorker(BaseException):
    pass


def _check_main_facade() -> None:
    tree = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8-sig"))
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "communication_workers":
            aliases.update({item.asname or item.name: item.name for item in node.names})
    assert aliases == EXPECTED_ALIASES
    definitions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not set(EXPECTED_ALIASES).intersection(definitions)


def _check_background_scale() -> None:
    with patch.object(communication_workers.db, "get_setting", return_value="0.1"):
        assert communication_workers.background_scale() == 0.25
    with patch.object(communication_workers.db, "get_setting", return_value="2"):
        assert communication_workers.background_scale() == 2.0
    with patch.object(communication_workers.db, "get_setting", side_effect=ValueError("invalid")):
        assert communication_workers.background_scale() == 1.0


async def _check_reminder_once() -> None:
    sleep_calls = 0

    async def controlled_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls > 1:
            raise StopWorker()

    notify = AsyncMock(return_value={"success": True})
    update = Mock()
    event = {
        "id": "evt-1",
        "title": "Intervention",
        "start_at": "2026-07-22 08:30:00",
        "location": "KOIOS",
    }
    with (
        patch.object(communication_workers.asyncio, "sleep", controlled_sleep),
        patch.object(communication_workers.db, "events_needing_reminder", return_value=[event]),
        patch.object(communication_workers.db, "update_event", update),
        patch.dict(communication_workers.tool_module.TOOLS_REGISTRY, {"pc_notify": notify}),
    ):
        try:
            await communication_workers.event_reminder_worker()
        except StopWorker:
            pass
        else:
            raise AssertionError("Le worker de test devait etre arrete apres un passage.")
    payload = notify.await_args.args[0]
    assert payload == {"title": "📅 Rappel : Intervention", "message": "À 08:30 (KOIOS)"}
    update.assert_called_once_with("evt-1", {"reminded": True})


def main() -> int:
    _check_main_facade()
    _check_background_scale()
    asyncio.run(_check_reminder_once())
    print("Communication Workers OK - facade, cadence et rappel agenda sans effet externe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
