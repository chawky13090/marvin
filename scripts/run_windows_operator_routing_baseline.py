"""Mesure le routage LLM réel sous verrou Forge, sans exécuter aucun outil."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "benchmarks" / "windows-operator" / "v1.1"
CAMPAIGNS = (ROOT / "benchmarks" / "windows-operator" / "campaigns").resolve()
_WINDOWS_TASK_FAMILIES = frozenset(
    {"application_launch", "process_action", "process_inventory", "security_posture"}
)


@contextmanager
def _campaign_mutex(output: Path):
    """Interdit deux producteurs Windows sur le meme artefact Forge."""
    identity = hashlib.sha256(
        str(output.resolve()).casefold().encode("utf-8")
    ).hexdigest()
    name = f"Local\\MarvinForgeRouting-{identity}"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_bool,
        ctypes.c_wchar_p,
    )
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.ReleaseMutex.argtypes = (ctypes.c_void_p,)
    kernel32.ReleaseMutex.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.CreateMutexW(None, True, name)
    if not handle:
        raise OSError(ctypes.get_last_error(), "Creation du mutex Forge impossible")
    if ctypes.get_last_error() == 183:
        kernel32.CloseHandle(handle)
        raise RuntimeError("Une campagne Forge ecrit deja cet artefact.")
    try:
        yield
    finally:
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON invalide : {path}")
    return payload


def _verify_manifest() -> dict[str, Any]:
    manifest = _read_json(CONTRACT / "corpus-manifest.json")
    if manifest.get("status") != "frozen_before_baseline":
        raise ValueError("Le corpus Forge n'est pas gelé.")
    for name, expected in manifest.get("files", {}).items():
        observed = hashlib.sha256((CONTRACT / name).read_bytes()).hexdigest()
        if observed != expected:
            raise ValueError(f"Dérive du corpus Forge : {name}")
    return manifest


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_family: dict[str, dict[str, Any]] = {}
    by_intent: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        family = str(row["family"])
        family_rows = by_family.setdefault(
            family,
            {"runs": 0, "passed": 0, "failed": 0, "selected": {}},
        )
        family_rows["runs"] += 1
        family_rows["passed" if row["passed"] else "failed"] += 1
        for name in row["selected_tools"]:
            family_rows["selected"][name] = family_rows["selected"].get(name, 0) + 1
        by_intent.setdefault(str(row["intent_id"]), []).append(row)
    for family_rows in by_family.values():
        family_rows["success_rate"] = round(
            family_rows["passed"] / family_rows["runs"], 4
        )
        family_rows["selected"] = dict(
            sorted(
                family_rows["selected"].items(),
                key=lambda item: (-item[1], item[0]),
            )
        )
    stable_intents = sum(
        len(
            {
                (row["terminal"], tuple(row["selected_tools"]))
                for row in intent_rows
            }
        )
        == 1
        for intent_rows in by_intent.values()
    )
    passed = sum(bool(row["passed"]) for row in results)
    return {
        "runs": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "success_rate": round(passed / len(results), 4) if results else 0,
        "forbidden_route_count": sum(bool(row["forbidden_match"]) for row in results),
        "false_success_measurable": False,
        "false_success_count": None,
        "stable_intents": stable_intents,
        "intent_count": len(by_intent),
        "repeat_stability_rate": (
            round(stable_intents / len(by_intent), 4) if by_intent else 0
        ),
        "median_duration_ms": (
            sorted(row["duration_ms"] for row in results)[len(results) // 2]
            if results
            else 0
        ),
        "by_family": dict(sorted(by_family.items())),
    }


async def _probe(
    client: httpx.AsyncClient,
    item: dict[str, Any],
    run: int,
    model: str,
    routing_policy: str,
) -> dict[str, Any]:
    started = time.monotonic()
    selected: list[str] = []
    original_selected: list[str] = []
    locked = False
    observed_model = ""
    terminal = "stream_ended"
    async with client.stream(
        "POST",
        "http://127.0.0.1:8005/api/chat",
        json={
            "messages": [{"role": "user", "content": item["prompt"]}],
            "model": model,
            "benchmarkEphemeral": True,
        },
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            event_type = str(event.get("type") or "")
            if event_type == "context_admission":
                locked = event.get("forgeLocked") is True
            elif event_type == "model_info":
                observed_model = str(event.get("model") or "")
            elif event_type == "benchmark_routing":
                selected = [str(name) for name in event.get("toolNames") or [] if str(name)]
                original_selected = [
                    str(name)
                    for name in event.get("originalToolNames") or selected
                    if str(name)
                ]
                terminal = "tool_selection"
                break
            elif event_type == "error":
                terminal = "error"
                break
            elif event_type == "done":
                terminal = "text_only"
                break
    expected = set(item["expected_tools"])
    if routing_policy == "windows_task" and item["family"] in _WINDOWS_TASK_FAMILIES:
        expected = {"windows_task"}
    forbidden = set(item["forbidden_tools"])
    passed = (
        locked
        and observed_model == model
        and not (forbidden & set(selected))
        and (bool(expected & set(selected)) if item["action_expected"] else not selected)
    )
    return {
        "intent_id": item["id"],
        "run": run,
        "family": item["family"],
        "terminal": terminal,
        "selected_tools": selected,
        "original_selected_tools": original_selected,
        "canonicalized": selected != original_selected,
        "expected_tools_effective": sorted(expected),
        "expected_match": bool(expected & set(selected)) if expected else not selected,
        "forbidden_match": bool(forbidden & set(selected)),
        "forge_locked": locked,
        "model_exact": observed_model == model,
        "passed": passed,
        "duration_ms": int((time.monotonic() - started) * 1000),
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
    corpus = _read_json(CONTRACT / "intent-corpus.json")
    items = [item for item in corpus["items"] if item["split"] == args.split]
    expected_runs = len(items) * args.runs
    payload = {
        "schema": (
            "marvin.windows-task-routing-candidate/1.0"
            if args.routing_policy == "windows_task"
            else "marvin.windows-operator-routing-baseline/1.1"
        ),
        "status": "running",
        "split": args.split,
        "model": model,
        "model_digest": runtime["model_digest"],
        "corpus_sha256": manifest["files"]["intent-corpus.json"],
        "runs_per_intent": args.runs,
        "routing_policy": args.routing_policy,
        "concurrency": args.concurrency,
        "expected_runs": expected_runs,
        "results": [],
    }
    if args.routing_policy == "windows_task":
        payload["source_hashes"] = {
            "agent.py": hashlib.sha256(
                (ROOT / "backend" / "agent.py").read_bytes()
            ).hexdigest(),
            "agent_tool_step.py": hashlib.sha256(
                (ROOT / "backend" / "agent_tool_step.py").read_bytes()
            ).hexdigest(),
            "agent_tool_selection.py": hashlib.sha256(
                (ROOT / "backend" / "agent_tool_selection.py").read_bytes()
            ).hexdigest(),
            "capability_catalog.py": hashlib.sha256(
                (ROOT / "backend" / "capability_catalog.py").read_bytes()
            ).hexdigest(),
            "capability_discovery.py": hashlib.sha256(
                (ROOT / "backend" / "capability_discovery.py").read_bytes()
            ).hexdigest(),
            "tools.py": hashlib.sha256(
                (ROOT / "backend" / "tools.py").read_bytes()
            ).hexdigest(),
            "windows_task.py": hashlib.sha256(
                (ROOT / "backend" / "windows_task.py").read_bytes()
            ).hexdigest(),
            "routing_runner.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
    if output.is_file():
        existing = _read_json(output)
        identity = (
            "model",
            "model_digest",
            "corpus_sha256",
            "split",
            "runs_per_intent",
            "routing_policy",
            "concurrency",
        )
        if args.routing_policy == "windows_task":
            identity += ("source_hashes",)
        if any(existing.get(key) != payload.get(key) for key in identity):
            raise ValueError("La reprise ne correspond pas au manifeste gelé.")
        payload = existing
    completed = {(row["intent_id"], int(row["run"])) for row in payload["results"]}
    jobs = [(item, run) for item in items for run in range(1, args.runs + 1) if (item["id"], run) not in completed]
    semaphore = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()
    async with httpx.AsyncClient(timeout=httpx.Timeout(args.timeout, connect=5)) as client:
        async def worker(item: dict[str, Any], run: int) -> None:
            async with semaphore:
                result = await _probe(client, item, run, model, args.routing_policy)
            async with lock:
                payload["results"].append(result)
                payload["results"].sort(key=lambda row: (row["intent_id"], row["run"]))
                _atomic_write(output, payload)

        await asyncio.gather(*(worker(item, run) for item, run in jobs))
    results = payload["results"]
    payload["status"] = "complete" if len(results) == expected_runs else "incomplete"
    payload["summary"] = _summarize(results)
    _atomic_write(output, payload)
    return {"output": str(output), "status": payload["status"], **payload["summary"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("development", "holdout"), default="development")
    parser.add_argument("--runs", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument(
        "--routing-policy",
        choices=("baseline", "windows_task"),
        default="baseline",
        help="Attentes historiques ou facade windows_task pour ses familles prises en charge.",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    with _campaign_mutex(output):
        result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
        print(f"Baseline Forge refusée : {exc}", file=sys.stderr)
        raise SystemExit(2)
