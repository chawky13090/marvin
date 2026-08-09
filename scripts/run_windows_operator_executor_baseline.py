"""Mesure les exécuteurs Windows existants avec fixtures et oracles indépendants."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CONTRACT = ROOT / "benchmarks" / "windows-operator" / "v1.1"
CAMPAIGNS = (ROOT / "benchmarks" / "windows-operator" / "campaigns").resolve()
sys.path.insert(0, str(BACKEND))

import windows_operator_fixtures as fixtures  # noqa: E402
from tool_domains import filesystem, pc_control, windows, winget  # noqa: E402


Executor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _resolve_fixture_path(raw: str) -> str:
    path = Path(raw).resolve()
    if path != fixtures.FIXTURE_ROOT and fixtures.FIXTURE_ROOT not in path.parents:
        raise ValueError("Le runner Forge refuse tout chemin hors de ses fixtures.")
    return str(path)


filesystem.configure(resolve_path=_resolve_fixture_path)
windows.configure(run_powershell=pc_control.execute_pc_run_powershell)


EXECUTORS: dict[str, Executor] = {
    "pc_process_list": pc_control.execute_pc_process_list,
    "pc_app_launch": pc_control.execute_pc_app_launch,
    "pc_process_kill": pc_control.execute_pc_process_kill,
    "win_services_list": windows.execute_win_services_list,
    "win_firewall_status": windows.execute_win_firewall_status,
    "win_network_config": windows.execute_win_network_config,
    "winget_list_installed": winget.execute_winget_list_installed,
    "file_create_folder": filesystem.create_folder,
    "file_rename": filesystem.rename,
    "file_copy": filesystem.copy,
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON invalide : {path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_manifest() -> dict[str, Any]:
    manifest = _read_json(CONTRACT / "corpus-manifest.json")
    if manifest.get("status") != "frozen_before_baseline":
        raise ValueError("Le corpus Forge n'est pas gelé.")
    for name, expected in manifest["files"].items():
        if _sha256(CONTRACT / name) != expected:
            raise ValueError(f"Dérive du corpus Forge : {name}")
    return manifest


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _arguments(scenario_id: str, context: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "process-list": {},
        "launch-notepad": {"app_name": "notepad"},
        "kill-fixture-process": {"pid": context.get("fixture_pid"), "confirmed": True},
        "services-list": {},
        "firewall-status": {},
        "network-config": {},
        "installed-software": {},
        "create-folder": {"path": context.get("target")},
        "rename-file": {
            "source": context.get("source"),
            "destination": context.get("target"),
        },
        "copy-file": {
            "source": context.get("source"),
            "destination": context.get("target"),
        },
    }
    if scenario_id not in mapping:
        raise KeyError(f"Scénario exécuteur inconnu : {scenario_id}")
    return mapping[scenario_id]


async def _execute_once(scenario: dict[str, Any], run: int) -> dict[str, Any]:
    run_id = f"executor-{scenario['id']}-{run}"
    context = fixtures.setup(str(scenario["fixture_id"]), run_id=run_id)
    capability = str(scenario["required_capabilities"][0])
    executor = EXECUTORS[capability]
    started = time.monotonic()
    tool_result: dict[str, Any] = {}
    oracle_result: dict[str, Any] = {"passed": False, "evidence": {}}
    teardown_clean = False
    try:
        tool_result = await asyncio.wait_for(
            executor(_arguments(str(scenario["id"]), context)),
            timeout=float(scenario["timeout_seconds"]),
        )
        oracle_result = fixtures.oracle(str(scenario["oracle_id"]), context)
    finally:
        root = Path(context["root"])
        teardown = fixtures.teardown(context)
        teardown_clean = bool(teardown.get("clean")) and not root.exists()
    tool_success = tool_result.get("success") is True
    tool_failed = bool(
        tool_result.get("error") or tool_result.get("requiresConfirmation")
    )
    completion_claimed = not tool_failed
    oracle_passed = oracle_result.get("passed") is True
    return {
        "scenario_id": scenario["id"],
        "run": run,
        "family": scenario["family"],
        "capability": capability,
        "tool_reported_success": tool_success,
        "tool_completion_claimed": completion_claimed,
        "tool_failed": tool_failed,
        "oracle_passed": oracle_passed,
        "false_success": completion_claimed and not oracle_passed,
        "false_failure": tool_failed and oracle_passed,
        "teardown_clean": teardown_clean,
        "passed": oracle_passed and teardown_clean,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "oracle_evidence": oracle_result.get("evidence") or {},
        "tool_error_type": "reported_error" if tool_result.get("error") else None,
    }


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(bool(row["passed"]) for row in results)
    return {
        "runs": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "success_rate": round(passed / len(results), 4) if results else 0,
        "false_success_count": sum(bool(row["false_success"]) for row in results),
        "false_failure_count": sum(bool(row["false_failure"]) for row in results),
        "teardown_failure_count": sum(not bool(row["teardown_clean"]) for row in results),
        "median_duration_ms": (
            sorted(row["duration_ms"] for row in results)[len(results) // 2]
            if results
            else 0
        ),
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _verify_manifest()
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output = output.resolve()
    if CAMPAIGNS not in output.parents or output.suffix.casefold() != ".json":
        raise ValueError("La baseline doit rester dans le dossier des campagnes.")
    contract = _read_json(CONTRACT / "live-scenarios.json")
    scenarios = [item for item in contract["scenarios"] if item["split"] == "development"]
    if len(scenarios) != 10:
        raise ValueError("Le split développement doit contenir exactement 10 scénarios.")
    expected_runs = len(scenarios) * args.runs
    payload = {
        "schema": "marvin.windows-operator-executor-baseline/1.1",
        "status": "running",
        "split": "development",
        "scenario_corpus_sha256": manifest["files"]["live-scenarios.json"],
        "runs_per_scenario": args.runs,
        "expected_runs": expected_runs,
        "executor_sources": {
            "filesystem.py": _sha256(BACKEND / "tool_domains" / "filesystem.py"),
            "pc_control.py": _sha256(BACKEND / "tool_domains" / "pc_control.py"),
            "windows.py": _sha256(BACKEND / "tool_domains" / "windows.py"),
            "winget.py": _sha256(BACKEND / "tool_domains" / "winget.py"),
        },
        "results": [],
    }
    if output.is_file():
        existing = _read_json(output)
        identity = (
            "scenario_corpus_sha256",
            "runs_per_scenario",
            "executor_sources",
        )
        if any(existing.get(key) != payload.get(key) for key in identity):
            raise ValueError("La reprise ne correspond pas aux exécuteurs gelés.")
        payload = existing
    completed = {(row["scenario_id"], int(row["run"])) for row in payload["results"]}
    for scenario in scenarios:
        for run in range(1, args.runs + 1):
            if (scenario["id"], run) in completed:
                continue
            payload["results"].append(await _execute_once(scenario, run))
            payload["results"].sort(key=lambda row: (row["scenario_id"], row["run"]))
            _atomic_write(output, payload)
    payload["status"] = (
        "complete" if len(payload["results"]) == expected_runs else "incomplete"
    )
    payload["summary"] = _summarize(payload["results"])
    _atomic_write(output, payload)
    return {"output": str(output), "status": payload["status"], **payload["summary"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, choices=range(1, 6), default=5)
    parser.add_argument("--output", required=True)
    result = asyncio.run(_run(parser.parse_args()))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError, asyncio.TimeoutError) as exc:
        print(f"Baseline exécuteur Forge refusée : {exc}", file=sys.stderr)
        raise SystemExit(2)
