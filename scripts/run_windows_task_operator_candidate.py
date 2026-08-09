"""Mesure windows_task en contournant la selection LLM.

Cette couche isole l'operateur type du routage et utilise les memes fixtures et
oracles independants que la baseline historique. Elle ne peut ecrire que dans
le repertoire versionne des campagnes Forge.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CONTRACT = ROOT / "benchmarks" / "windows-operator" / "v1.1"
CAMPAIGNS = (ROOT / "benchmarks" / "windows-operator" / "campaigns").resolve()
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(BACKEND))

import run_windows_operator_executor_baseline as legacy  # noqa: E402
import windows_operator_fixtures as fixtures  # noqa: E402
import windows_task  # noqa: E402


windows_task.configure(legacy.EXECUTORS)


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
        raise ValueError("Le corpus Forge n'est pas gele.")
    for name, expected in manifest["files"].items():
        if _sha256(CONTRACT / name) != expected:
            raise ValueError(f"Derive du corpus Forge : {name}")
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
        "process-list": {"action": "process.list"},
        "launch-notepad": {
            "action": "application.launch",
            "target": "notepad",
            "confirmed": True,
        },
        "kill-fixture-process": {
            "action": "process.stop",
            "pid": context.get("fixture_pid"),
            "confirmed": True,
        },
        "services-list": {"action": "service.list"},
        "firewall-status": {"action": "security.firewall.status"},
        "network-config": {"action": "network.status"},
        "installed-software": {"action": "software.list"},
        "create-folder": {
            "action": "filesystem.create_folder",
            "target": context.get("target"),
            "confirmed": True,
        },
        "rename-file": {
            "action": "filesystem.rename",
            "source": context.get("source"),
            "destination": context.get("target"),
            "confirmed": True,
        },
        "copy-file": {
            "action": "filesystem.copy",
            "source": context.get("source"),
            "destination": context.get("target"),
            "confirmed": True,
        },
    }
    if scenario_id not in mapping:
        raise KeyError(f"Scenario windows_task inconnu : {scenario_id}")
    return mapping[scenario_id]


async def _execute_once(scenario: dict[str, Any], run: int) -> dict[str, Any]:
    run_id = f"windows-task-{scenario['id']}-{run}"
    context = fixtures.setup(str(scenario["fixture_id"]), run_id=run_id)
    started = time.monotonic()
    tool_result: dict[str, Any] = {}
    oracle_result: dict[str, Any] = {"passed": False, "evidence": {}}
    teardown_clean = False
    try:
        tool_result = await asyncio.wait_for(
            windows_task.execute(_arguments(str(scenario["id"]), context)),
            timeout=float(scenario["timeout_seconds"]),
        )
        oracle_result = fixtures.oracle(str(scenario["oracle_id"]), context)
    finally:
        root = Path(context["root"])
        teardown = fixtures.teardown(context)
        teardown_clean = bool(teardown.get("clean")) and not root.exists()
    tool_failed = bool(
        tool_result.get("error") or tool_result.get("requiresConfirmation")
    )
    completion_claimed = not tool_failed and tool_result.get("effect_verified") is True
    oracle_passed = oracle_result.get("passed") is True
    return {
        "scenario_id": scenario["id"],
        "run": run,
        "family": scenario["family"],
        "operator": "windows_task",
        "compiled_executor": tool_result.get("executor"),
        "tool_completion_claimed": completion_claimed,
        "tool_failed": tool_failed,
        "effect_verified": tool_result.get("effect_verified") is True,
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
        "effect_verified_count": sum(bool(row["effect_verified"]) for row in results),
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
        raise ValueError("La campagne doit rester dans le dossier Forge.")
    contract = _read_json(CONTRACT / "live-scenarios.json")
    scenarios = [item for item in contract["scenarios"] if item["split"] == "development"]
    if len(scenarios) != 10:
        raise ValueError("Le split developpement doit contenir 10 scenarios.")
    expected_runs = len(scenarios) * args.runs
    payload = {
        "schema": "marvin.windows-task-operator-candidate/1.0",
        "status": "running",
        "split": "development",
        "scenario_corpus_sha256": manifest["files"]["live-scenarios.json"],
        "runs_per_scenario": args.runs,
        "expected_runs": expected_runs,
        "source_hashes": {
            "windows_task.py": _sha256(BACKEND / "windows_task.py"),
            "windows_operator_fixtures.py": _sha256(
                BACKEND / "windows_operator_fixtures.py"
            ),
            "filesystem.py": _sha256(BACKEND / "tool_domains" / "filesystem.py"),
            "pc_control.py": _sha256(BACKEND / "tool_domains" / "pc_control.py"),
            "windows.py": _sha256(BACKEND / "tool_domains" / "windows.py"),
            "winget.py": _sha256(BACKEND / "tool_domains" / "winget.py"),
            "legacy_runner.py": _sha256(
                ROOT / "scripts" / "run_windows_operator_executor_baseline.py"
            ),
            "candidate_runner.py": _sha256(Path(__file__)),
        },
        "results": [],
    }
    if output.is_file():
        existing = _read_json(output)
        identity = (
            "scenario_corpus_sha256",
            "runs_per_scenario",
            "source_hashes",
        )
        if any(existing.get(key) != payload.get(key) for key in identity):
            raise ValueError("La reprise ne correspond pas au candidat gele.")
        payload = existing
    completed = {(row["scenario_id"], int(row["run"])) for row in payload["results"]}
    for scenario in scenarios:
        for run in range(1, args.runs + 1):
            if (scenario["id"], run) in completed:
                continue
            payload["results"].append(await _execute_once(scenario, run))
            payload["results"].sort(key=lambda row: (row["scenario_id"], row["run"]))
            _atomic_write(output, payload)
    payload["status"] = "complete" if len(payload["results"]) == expected_runs else "incomplete"
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
        print(f"Campagne windows_task refusee : {exc}", file=sys.stderr)
        raise SystemExit(2)
