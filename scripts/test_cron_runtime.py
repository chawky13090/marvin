"""Regressions deterministes du moteur cron et de la reprise longue."""

from __future__ import annotations

import ast
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import cron_runtime


EXPECTED_IMPORTS = {
    "_cron_worker": "cron_worker",
    "_drain_run_agent": "drain_run_agent",
    "_long_task_resume_tick": "long_task_resume_tick",
}


class StopWorker(BaseException):
    pass


def _check_main_facade() -> None:
    tree = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8-sig"))
    imports: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "cron_runtime":
            imports.update({item.asname or item.name: item.name for item in node.names})
    assert imports == EXPECTED_IMPORTS
    definitions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not set(EXPECTED_IMPORTS).intersection(definitions)


async def _check_malformed_long_task() -> None:
    update = Mock()
    with patch.object(cron_runtime.db, "update_cron_job", update):
        await cron_runtime.long_task_resume_tick(
            {"id": "cron-1", "args": {}, "schedule": "*/5 * * * *"},
            "2026-07-22 10:00:00",
        )
    payload = update.call_args.args[1]
    assert payload["enabled"] is False
    assert json.loads(payload["last_result"])["error"] == "job long_task mal formé"


async def _check_completed_long_task() -> None:
    update = Mock()
    notify = AsyncMock(return_value={"success": True})
    job = {
        "id": "cron-2",
        "args": {"conversation_id": "conv", "slug": "done", "goal": "Livrer"},
        "schedule": "*/5 * * * *",
    }
    with (
        patch.object(cron_runtime.db, "list_tasks", return_value=[]),
        patch.object(cron_runtime.db, "update_cron_job", update),
        patch.dict(cron_runtime.tool_module.TOOLS_REGISTRY, {"pc_notify": notify}),
    ):
        await cron_runtime.long_task_resume_tick(job, "2026-07-22 10:00:00")
    assert update.call_args.args[1]["enabled"] is False
    notify.assert_awaited_once()


async def _check_regular_job_once() -> None:
    executor = AsyncMock(return_value={"success": True})
    log_execution = Mock()
    update = Mock()
    job = {
        "id": "cron-3",
        "tool_name": "safe_test_tool",
        "args": {"value": 7},
        "schedule": "*/5 * * * *",
        "next_run": None,
    }

    async def stop_after_pass(_seconds: float) -> None:
        raise StopWorker()

    with (
        patch.object(cron_runtime.db, "list_cron_jobs", return_value=[job]),
        patch.object(cron_runtime.db, "log_execution", log_execution),
        patch.object(cron_runtime.db, "update_cron_job", update),
        patch.object(cron_runtime, "next_run_datetime", return_value="2026-07-22 10:05:00"),
        patch.object(cron_runtime.asyncio, "sleep", stop_after_pass),
        patch.dict(cron_runtime.tool_module.TOOLS_REGISTRY, {"safe_test_tool": executor}),
    ):
        try:
            await cron_runtime.cron_worker()
        except StopWorker:
            pass
        else:
            raise AssertionError("Le worker de test devait etre arrete apres un cycle.")
    executor.assert_awaited_once_with({"value": 7})
    log_execution.assert_called_once()
    payload = update.call_args.args[1]
    assert payload["next_run"] == "2026-07-22 10:05:00"
    assert payload["run_count"] is True
    assert json.loads(payload["last_result"]) == {"success": True}


def main() -> int:
    _check_main_facade()
    asyncio.run(_check_malformed_long_task())
    asyncio.run(_check_completed_long_task())
    asyncio.run(_check_regular_job_once())
    print("Cron Runtime OK - facade, jobs standards et fins de missions longues.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
