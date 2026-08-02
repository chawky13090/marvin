"""Contrat du composition root FastAPI et de son cycle de vie."""

from __future__ import annotations

import ast
import asyncio
import subprocess
import sys
import time
import types
from pathlib import Path

from repository_test_scope import backend_python_files
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import main as main_module


EXPECTED_FUNCTIONS = {"lifespan", "_global_exception_handler"}
EXPECTED_WORKERS = {
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
    "model-catalog-watch",
    "engineering-radar",
}


def _check_static_composition() -> None:
    source = (BACKEND / "main.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert definitions == EXPECTED_FUNCTIONS
    assert len(source.splitlines()) <= 350

    api_modules = {
        path.stem
        for path in (BACKEND / "api").glob("*.py")
        if path.name != "__init__.py"
    }
    mounted: set[str] = set()
    imported: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("api."):
            for item in node.names:
                if item.name == "router" and item.asname:
                    imported[item.asname] = node.module.removeprefix("api.")
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "app"
            and node.value.func.attr == "include_router"
            and node.value.args
            and isinstance(node.value.args[0], ast.Name)
        ):
            mounted.add(node.value.args[0].id)
    assert set(imported.values()) == api_modules
    assert mounted == set(imported)

    used_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    unused: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = [(item.asname or item.name.split(".", 1)[0]) for item in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            names = [(item.asname or item.name) for item in node.names]
        else:
            continue
        unused.update(name for name in names if name not in used_names)
    assert unused == set()


def _first_party_import_graph() -> dict[str, set[str]]:
    modules = {
        ".".join(path.relative_to(BACKEND).with_suffix("").parts): path
        for path in backend_python_files(BACKEND)
    }
    modules = {
        (name.removesuffix(".__init__")): path
        for name, path in modules.items()
    }
    graph = {name: set() for name in modules}
    for name, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in tree.body:
            if isinstance(node, ast.Import):
                imported_names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names = [node.module]
            else:
                continue
            for imported_name in imported_names:
                candidates = [
                    candidate
                    for candidate in modules
                    if imported_name == candidate or imported_name.startswith(candidate + ".")
                ]
                if candidates:
                    graph[name].add(max(candidates, key=len))
    return graph


def _check_no_top_level_import_cycle() -> None:
    graph = _first_party_import_graph()
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, path: tuple[str, ...]) -> None:
        if node in visiting:
            start = path.index(node)
            raise AssertionError("Cycle d'import : " + " -> ".join(path[start:] + (node,)))
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency, path + (node,))
        visiting.remove(node)
        visited.add(node)

    for module_name in graph:
        visit(module_name, ())


def _check_bounded_clean_import() -> None:
    started = time.monotonic()
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import main; print(main.app.version, len(main.app.routes))",
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    duration = time.monotonic() - started
    assert completed.returncode == 0, completed.stderr
    assert main_module.APP_VERSION in completed.stdout
    assert duration < 30


async def _check_lifespan() -> None:
    events: list[str] = []

    class Supervisor:
        def __init__(self) -> None:
            self.names: list[str] = []

        def start(self, name: str, _factory) -> None:
            self.names.append(name)

        async def shutdown(self) -> None:
            events.append("supervisor.shutdown")

    supervisor = Supervisor()
    app = types.SimpleNamespace(state=types.SimpleNamespace())
    coding_jobs = types.SimpleNamespace(
        start_pending=Mock(side_effect=lambda: events.append("coding.start")),
        shutdown=AsyncMock(side_effect=lambda: events.append("coding.shutdown")),
    )
    auto_config = types.SimpleNamespace(
        apply_auto_config=AsyncMock(return_value={"enabled": False})
    )
    skills = types.SimpleNamespace(seed_examples=Mock())
    web_browser = types.SimpleNamespace(
        close=AsyncMock(side_effect=lambda: events.append("browser.close"))
    )
    engineering_radar = types.SimpleNamespace(background_worker=AsyncMock())
    model_market = types.SimpleNamespace(sync_recommended_cloud_models=AsyncMock())

    with (
        patch.object(main_module, "RuntimeSupervisor", return_value=supervisor),
        patch.object(main_module.chat_turn_runtime, "recover_orphaned_turns") as recover,
        patch.object(main_module.chat_turn_runtime, "prune") as prune,
        patch.object(
            main_module.chat_turn_runtime,
            "shutdown",
            new=AsyncMock(side_effect=lambda: events.append("chat.shutdown")),
        ),
        patch.object(main_module, "_refresh_model_cache", new=AsyncMock()),
        patch.object(
            main_module.generation_runtime,
            "close",
            new=AsyncMock(side_effect=lambda: events.append("generation.close")),
        ),
        patch.object(
            main_module.web_runtime,
            "close",
            new=AsyncMock(side_effect=lambda: events.append("web.close")),
        ),
        patch.dict(
            sys.modules,
            {
                "auto_config": auto_config,
                "coding_jobs": coding_jobs,
                "engineering_radar": engineering_radar,
                "model_market": model_market,
                "skills": skills,
                "web_browser": web_browser,
            },
        ),
    ):
        async with main_module.lifespan(app):
            assert app.state.runtime_supervisor is supervisor
            assert set(supervisor.names) == EXPECTED_WORKERS
            assert len(supervisor.names) == len(EXPECTED_WORKERS)
            recover.assert_called_once()
            prune.assert_called_once()
            skills.seed_examples.assert_called_once()

    assert events == [
        "coding.start",
        "chat.shutdown",
        "coding.shutdown",
        "supervisor.shutdown",
        "browser.close",
        "generation.close",
        "web.close",
    ]


def main() -> int:
    _check_static_composition()
    _check_no_top_level_import_cycle()
    _check_bounded_clean_import()
    asyncio.run(_check_lifespan())
    print(
        "Main composition OK - root minimal, routeurs complets, imports acycliques "
        "et lifecycle ferme."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
