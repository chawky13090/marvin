"""Caracterisation sans effet de bord des workers extraits de main.py."""

from __future__ import annotations

import ast
import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import config
import runtime_workers


EXPECTED_ALIASES = {
    "_prewarm_default_model": "prewarm_default_models",
    "_build_tool_index": "build_tool_index",
    "_skill_night_learning_worker": "skill_night_learning_worker",
    "_db_backup_worker": "database_backup_worker",
    "_memory_consolidation_worker": "memory_consolidation_worker",
    "_health_trend_worker": "health_trend_worker",
}

EXPECTED_RUNTIME_TASKS = {
    "cron",
    "ollama-prewarm",
    "whisper-prewarm",
    "email-watch",
    "email-automation",
    "event-reminders",
    "calendar-sync",
    "proactive-briefing",
    "skill-night-learning",
    "tool-index",
    "database-backup",
    "memory-consolidation",
    "health-trend",
    "cloud-model-fleet",
    "engineering-radar",
}


def _check_main_contract() -> None:
    tree = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8-sig"))
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "runtime_workers":
            aliases.update({item.asname or item.name: item.name for item in node.names})
    assert aliases == EXPECTED_ALIASES
    definitions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not set(EXPECTED_ALIASES).intersection(definitions)

    task_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if (
            isinstance(node.func.value, ast.Name)
            and node.func.value.id == "supervisor"
            and node.func.attr == "start"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            task_names.add(node.args[0].value)
    assert task_names == EXPECTED_RUNTIME_TASKS


async def _check_prewarm_deduplication() -> None:
    calls: list[tuple[str, dict]] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 120.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url: str, *, json: dict):
            calls.append((url, json))

    profiles = {"agent": {"model": "same:cloud"}, "chat": {"model": "same:cloud"}}
    import httpx
    import cloud_routing

    with (
        patch.object(config, "MODEL_PROFILES", profiles),
        patch.object(config, "OLLAMA_URL", "http://ollama.invalid"),
        patch.object(cloud_routing, "get_cloud_config", return_value=(False, {})),
        patch.object(cloud_routing, "is_local_only_lockdown", return_value=False),
        patch.object(httpx, "AsyncClient", FakeClient),
    ):
        await runtime_workers.prewarm_default_models()
    assert len(calls) == 1
    assert calls[0][0] == "http://ollama.invalid/api/chat"
    assert calls[0][1]["model"] == "same:cloud"
    assert calls[0][1]["keep_alive"] == "30m"

    calls.clear()
    with (
        patch.object(config, "MODEL_PROFILES", profiles),
        patch.object(config, "OLLAMA_URL", "http://ollama.invalid"),
        patch.object(cloud_routing, "get_cloud_config", return_value=(True, {
            "agent": "frontier:cloud",
        })),
        patch.object(cloud_routing, "is_local_only_lockdown", return_value=False),
        patch.object(httpx, "AsyncClient", FakeClient),
    ):
        await runtime_workers.prewarm_default_models()
    assert calls == []


async def _check_tool_index() -> None:
    received = None

    async def ensure_tool_index(spec):
        nonlocal received
        received = spec
        return True

    fake_router = types.SimpleNamespace(ensure_tool_index=ensure_tool_index)
    with (
        patch.object(runtime_workers.asyncio, "sleep", AsyncMock()),
        patch.dict(sys.modules, {"tool_router": fake_router}),
    ):
        await runtime_workers.build_tool_index()
    assert received is runtime_workers.tool_module.TOOLS_SPEC


def main() -> int:
    _check_main_contract()
    asyncio.run(_check_prewarm_deduplication())
    asyncio.run(_check_tool_index())
    print("Runtime Workers OK - facade main, 15 taches, prewarm deduplique et index outils.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
