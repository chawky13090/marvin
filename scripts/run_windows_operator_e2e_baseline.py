"""Mesure le parcours Marvin complet sur les scénarios Windows de développement."""

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

import httpx


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CONTRACT = ROOT / "benchmarks" / "windows-operator" / "v1.1"
CAMPAIGNS = (ROOT / "benchmarks" / "windows-operator" / "campaigns").resolve()
sys.path.insert(0, str(BACKEND))

import windows_operator_fixtures as fixtures  # noqa: E402


CORTEX = {
    "effort": "standard",
    "evidence": "none",
    "review": "none",
    "autonomy": "execute",
    "privacy": "cloud",
    "output": "chat",
    "pinned": True,
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


def _tool_claim(event: dict[str, Any]) -> tuple[bool, bool]:
    result = event.get("result")
    if not isinstance(result, dict):
        return False, False
    failed = bool(result.get("error") or result.get("requiresConfirmation"))
    return not failed, failed


def _classify_tool_end(
    event: dict[str, Any], target_capability: str
) -> tuple[bool, bool, bool]:
    """Retourne claim cible, echec cible, echec incident non cible."""
    claimed, failed = _tool_claim(event)
    is_target = str(event.get("toolName") or "") == target_capability
    return claimed and is_target, failed and is_target, failed and not is_target


async def _probe(
    client: httpx.AsyncClient,
    scenario: dict[str, Any],
    run: int,
    model: str,
) -> dict[str, Any]:
    run_id = f"e2e-{scenario['id']}-{run}"
    context = fixtures.setup(str(scenario["fixture_id"]), run_id=run_id)
    prompt = fixtures.enrich_prompt(str(scenario["prompt"]), context)
    started = time.monotonic()
    conversation_id = ""
    selected_tools: list[str] = []
    target_capability = str(scenario["required_capabilities"][0])
    target_completion_claimed = False
    target_tool_failed = False
    incidental_tool_failed = False
    forge_locked = False
    model_exact = False
    terminal = "stream_ended"
    oracle_result: dict[str, Any] = {"passed": False, "evidence": {}}
    teardown_clean = False
    try:
        async with client.stream(
            "POST",
            "http://127.0.0.1:8005/api/chat",
            json={
                "messages": [{"role": "user", "content": prompt}],
                "model": model,
                "cortex": CORTEX,
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                event_type = str(event.get("type") or "")
                if event_type == "conv_id":
                    conversation_id = str(event.get("conversationId") or "")
                elif event_type == "context_admission":
                    forge_locked = event.get("forgeLocked") is True
                elif event_type == "model_info":
                    model_exact = str(event.get("model") or "") == model
                elif event_type == "tool_start":
                    name = str(event.get("toolName") or "")
                    if name:
                        selected_tools.append(name)
                elif event_type == "tool_end":
                    target_claim, target_failure, incidental_failure = (
                        _classify_tool_end(event, target_capability)
                    )
                    target_completion_claimed |= target_claim
                    target_tool_failed |= target_failure
                    incidental_tool_failed |= incidental_failure
                elif event_type == "done":
                    terminal = "done"
                    break
                elif event_type == "error":
                    terminal = "error"
                    break
        oracle_result = fixtures.oracle(str(scenario["oracle_id"]), context)
    finally:
        if conversation_id:
            try:
                response = await client.delete(
                    f"http://127.0.0.1:8005/api/conversations/{conversation_id}"
                )
                response.raise_for_status()
            except httpx.HTTPError:
                terminal = "conversation_cleanup_failed"
        root = Path(context["root"])
        teardown = fixtures.teardown(context)
        teardown_clean = bool(teardown.get("clean")) and not root.exists()
    oracle_passed = oracle_result.get("passed") is True
    return {
        "scenario_id": scenario["id"],
        "run": run,
        "family": scenario["family"],
        "target_capability": target_capability,
        "terminal": terminal,
        "selected_tools": selected_tools,
        "forge_locked": forge_locked,
        "model_exact": model_exact,
        "target_completion_claimed": target_completion_claimed,
        "target_tool_failed": target_tool_failed,
        "incidental_tool_failed": incidental_tool_failed,
        "oracle_passed": oracle_passed,
        "false_success": target_completion_claimed and not oracle_passed,
        "target_false_failure": target_tool_failed and oracle_passed,
        "recovered_incidental_failure": incidental_tool_failed and oracle_passed,
        "teardown_clean": teardown_clean,
        "passed": oracle_passed and forge_locked and model_exact and teardown_clean,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "oracle_evidence": oracle_result.get("evidence") or {},
    }


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(bool(row["passed"]) for row in results)
    return {
        "runs": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "success_rate": round(passed / len(results), 4) if results else 0,
        "false_success_count": sum(bool(row["false_success"]) for row in results),
        "target_false_failure_count": sum(
            bool(row["target_false_failure"]) for row in results
        ),
        "recovered_incidental_failure_count": sum(
            bool(row["recovered_incidental_failure"]) for row in results
        ),
        "technical_error_count": sum(row["terminal"] == "error" for row in results),
        "cleanup_failure_count": sum(
            row["terminal"] == "conversation_cleanup_failed"
            or not bool(row["teardown_clean"])
            for row in results
        ),
        "median_duration_ms": (
            sorted(row["duration_ms"] for row in results)[len(results) // 2]
            if results
            else 0
        ),
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _verify_manifest()
    runtime = manifest["runtime_precondition"]
    model = str(runtime["model"])
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output = output.resolve()
    if CAMPAIGNS not in output.parents or output.suffix.casefold() != ".json":
        raise ValueError("La baseline doit rester dans le dossier des campagnes.")
    contract = _read_json(CONTRACT / "live-scenarios.json")
    scenarios = [item for item in contract["scenarios"] if item["split"] == "development"]
    expected_runs = len(scenarios) * args.runs
    payload = {
        "schema": "marvin.windows-operator-e2e-baseline/1.2",
        "status": "running",
        "split": "development",
        "model": model,
        "model_digest": runtime["model_digest"],
        "scenario_corpus_sha256": manifest["files"]["live-scenarios.json"],
        "cortex": CORTEX,
        "runs_per_scenario": args.runs,
        "expected_runs": expected_runs,
        "results": [],
    }
    if output.is_file():
        existing = _read_json(output)
        identity = (
            "schema",
            "model",
            "model_digest",
            "scenario_corpus_sha256",
            "cortex",
            "runs_per_scenario",
        )
        if any(existing.get(key) != payload.get(key) for key in identity):
            raise ValueError("La reprise ne correspond pas au manifeste gelé.")
        payload = existing
    completed = {(row["scenario_id"], int(row["run"])) for row in payload["results"]}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(args.timeout, connect=5)
    ) as client:
        for scenario in scenarios:
            for run in range(1, args.runs + 1):
                if (scenario["id"], run) in completed:
                    continue
                payload["results"].append(await _probe(client, scenario, run, model))
                payload["results"].sort(
                    key=lambda row: (row["scenario_id"], row["run"])
                )
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
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--output", required=True)
    result = asyncio.run(_run(parser.parse_args()))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError, httpx.HTTPError) as exc:
        print(f"Baseline E2E Forge refusée : {exc}", file=sys.stderr)
        raise SystemExit(2)
