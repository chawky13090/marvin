"""Compare le chemin actuel et la façade v1.3 sans exécuter aucun outil métier."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from jsonschema import Draft202012Validator
from qdrant_client import QdrantClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

import agent_prompt
import agent_tool_selection as selection
import database as db
import run_tool_selection_ablation as stage_a
import tool_router
from config import OLLAMA_URL, QDRANT_PATH
from tool_canonical_facade import build_canonical_tool_view


BASE = ROOT / "benchmarks/tool-selection/v1.3"
CORPUS = BASE / "holdout-corpus.json"
ORACLE = BASE / "holdout-oracle.json"
CONTROL = BASE / "control-corpus.json"
HOLDOUT_FREEZE = BASE / "holdout-freeze-manifest.json"
RUNNER_FREEZE = BASE / "ab-runner-freeze.json"
AUTHORIZATION = BASE / "ab-authorization.json"
RESULT = BASE / "ab-result.json"
OLLAMA = OLLAMA_URL.rstrip("/")
MODES = {"eco": 18, "balanced": 40, "performance": 80}
VARIANTS = ("current", "canonical_facade")
FIXED_NOW = datetime(2026, 8, 14, 12, 0, 0)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _atomic(path: Path, value: Any) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _tool_call(message: dict[str, Any]) -> tuple[str | None, dict[str, Any], int]:
    calls = message.get("tool_calls") or []
    if not isinstance(calls, list) or len(calls) != 1:
        return None, {}, len(calls) if isinstance(calls, list) else 0
    function = calls[0].get("function") or {}
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}
    return str(function.get("name") or "") or None, arguments if isinstance(arguments, dict) else {}, 1


def _accepted(name: str | None, arguments: dict[str, Any], calls: list[dict[str, Any]]) -> bool:
    if not name:
        return False
    for expected in calls:
        if name != expected["tool"]:
            continue
        if expected.get("action") is not None and arguments.get("action") != expected["action"]:
            continue
        valid = True
        for constraint in expected.get("constraints") or []:
            key = constraint["argument"]
            if constraint["operator"] == "present" and key not in arguments:
                valid = False
            if constraint["operator"] == "equals" and arguments.get(key) != constraint.get("value"):
                valid = False
        if valid:
            return True
    return False


def _schema_valid(name: str | None, arguments: dict[str, Any], by_name: dict[str, dict[str, Any]]) -> bool:
    if not name or name not in by_name:
        return False
    schema = by_name[name]["function"].get("parameters") or {"type": "object"}
    return not list(Draft202012Validator(schema).iter_errors(arguments))


async def _benchmark_call(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    *,
    model: str,
    system_prompt: str,
    prompt: str,
    tools: list[dict[str, Any]],
    seed: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
        "tools": tools,
        "options": {"temperature": 0.1, "top_p": 0.9, "seed": seed, "num_predict": 512},
    }
    assert "num_ctx" not in payload["options"]
    started = time.perf_counter()
    async with semaphore:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = await client.post(f"{OLLAMA}/api/chat", json=payload)
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError("Cloud 5xx", request=response.request, response=response)
                response.raise_for_status()
                body = response.json()
                name, arguments, count = _tool_call(body.get("message") or {})
                return {
                    "observed_model": str(body.get("model") or ""),
                    "name": name,
                    "arguments": arguments,
                    "call_count": count,
                    "prompt_eval_count": int(body.get("prompt_eval_count") or 0),
                    "eval_count": int(body.get("eval_count") or 0),
                    "attempts": attempt,
                    "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
                }
            except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as exc:
                last_error = exc
                if attempt < 3:
                    await asyncio.sleep(float(attempt))
        raise RuntimeError("Appel benchmark indisponible après trois tentatives.") from last_error


async def _candidate_specs(records: list[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    client = QdrantClient(path=QDRANT_PATH)
    try:
        collections = {item.name for item in client.get_collections().collections}
        if tool_router._TOOL_COLLECTION not in collections:
            raise RuntimeError("Index sémantique des outils absent.")
        if db.get_setting("tool_index_hash") != tool_router.tool_index_fingerprint(selection.TOOLS_SPEC):
            raise RuntimeError("Index sémantique des outils périmé.")
        lexical, semantic, _metadata = await stage_a._signals(
            records, client, batch_size=16, control_query_count=5
        )
    finally:
        client.close()
    matrix, _costs = await stage_a._candidate_matrix(
        records,
        modes=MODES,
        lexical_cache=lexical,
        semantic_cache=semantic,
    )
    output: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for mode in MODES:
        for row in records:
            names = matrix[mode]["K+L+S"][row["id"]]
            output[(mode, row["id"])] = [
                specification for specification in selection.TOOLS_SPEC
                if specification["function"]["name"] in names
            ]
    return output


async def run(*, preflight_only: bool) -> dict[str, Any]:
    freeze = json.loads(HOLDOUT_FREEZE.read_text(encoding="utf-8"))
    for relative, expected in freeze["frozen_hashes"].items():
        if _sha(ROOT / relative) != expected:
            raise RuntimeError(f"Holdout modifié après gel: {relative}")
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))["items"]
    oracle = {
        row["id"]: row["accepted_calls"]
        for row in json.loads(ORACLE.read_text(encoding="utf-8"))["items"]
    }
    controls = json.loads(CONTROL.read_text(encoding="utf-8"))["items"]
    records = [{"id": row["id"], "query": row["prompt"]} for row in corpus]
    specifications = await _candidate_specs(records)
    all_names = {str(item["function"]["name"]) for item in selection.TOOLS_SPEC}
    views: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    activation: dict[tuple[str, str], dict[str, Any]] = {}
    for mode in MODES:
        for row in corpus:
            baseline = specifications[(mode, row["id"])]
            views[(mode, row["id"], "current")] = baseline
            candidate = build_canonical_tool_view(
                row["prompt"], baseline, all_tool_names=all_names, enabled=True
            )
            views[(mode, row["id"], "canonical_facade")] = list(candidate.tools)
            activation[(mode, row["id"])] = {
                "active": candidate.active,
                "status": candidate.status,
                "capability_id": candidate.decision.capability_id if candidate.decision else None,
            }
    control_activation = []
    for row in controls:
        baseline = selection.TOOLS_SPEC
        candidate = build_canonical_tool_view(row["prompt"], baseline, all_tool_names=all_names, enabled=True)
        control_activation.append({
            "id": row["id"],
            "active": candidate.active,
            "baseline_names_sha256": hashlib.sha256(_canonical([item["function"]["name"] for item in baseline])).hexdigest(),
            "candidate_names_sha256": hashlib.sha256(_canonical([item["function"]["name"] for item in candidate.tools])).hexdigest(),
        })
    preflight = {
        "status": "preflight_complete",
        "holdout_count": len(corpus),
        "view_count": len(views),
        "facade_activation_count": sum(item["active"] for item in activation.values()),
        "facade_expected_activation_count": len(corpus) * len(MODES),
        "control_count": len(control_activation),
        "control_activation_count": sum(item["active"] for item in control_activation),
        "control_candidate_equality_count": sum(
            item["baseline_names_sha256"] == item["candidate_names_sha256"]
            for item in control_activation
        ),
        "business_tool_execution_count": 0,
        "benchmark_model_call_count": 0,
    }
    if preflight_only:
        return preflight

    runner_freeze = json.loads(RUNNER_FREEZE.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    if RESULT.exists():
        raise RuntimeError("Résultat A/B déjà publié; autorisation consommée.")
    for relative, expected in runner_freeze["frozen_hashes"].items():
        if _sha(ROOT / relative) != expected:
            raise RuntimeError(f"Runner modifié après gel: {relative}")
    if authorization["runner_freeze_sha256"] != _sha(RUNNER_FREEZE):
        raise RuntimeError("Autorisation non liée au runner.")
    if not authorization["benchmark_model_calls"] or authorization["business_tool_execution"]:
        raise RuntimeError("Autorisation A/B invalide.")

    benchmark = runner_freeze["benchmark"]
    system_prompt = agent_prompt.build_system_prompt([], 2, now=FIXED_NOW, compact=False)
    tasks: list[Any] = []
    descriptors: list[tuple[dict[str, Any], str, str, int, list[dict[str, Any]]]] = []
    async with httpx.AsyncClient(timeout=600, trust_env=False) as client:
        tags = (await client.get(f"{OLLAMA}/api/tags")).json().get("models") or []
        model_row = next((row for row in tags if row.get("name") == benchmark["model"]), None)
        if not model_row or model_row.get("digest") != benchmark["digest"] or not model_row.get("remote_host"):
            raise RuntimeError("Provenance du modèle benchmark invalide.")
        semaphore = asyncio.Semaphore(int(runner_freeze["concurrency_maximum"]))
        for row_index, row in enumerate(corpus):
            for repetition in range(1, int(runner_freeze["repetitions_per_intent"]) + 1):
                variants = VARIANTS[row_index % 2:] + VARIANTS[:row_index % 2]
                for mode in MODES:
                    for variant in variants:
                        specs = views[(mode, row["id"], variant)]
                        descriptors.append((row, mode, variant, repetition, specs))
                        tasks.append(_benchmark_call(
                            client,
                            semaphore,
                            model=benchmark["model"],
                            system_prompt=system_prompt,
                            prompt=row["prompt"],
                            tools=specs,
                            seed=int(runner_freeze["seed"]),
                        ))
        raw = await asyncio.gather(*tasks)

    observations = []
    for descriptor, observed in zip(descriptors, raw, strict=True):
        row, mode, variant, repetition, specs = descriptor
        by_name = {str(item["function"]["name"]): item for item in specs}
        name, arguments = observed["name"], observed["arguments"]
        observed.update({
            "id": row["id"],
            "family": row["family"],
            "mode": mode,
            "variant": variant,
            "repetition": repetition,
            "candidate_count": len(specs),
            "prompt_schema_bytes": len(_canonical(specs)),
            "candidate_membership_valid": name is None or name in by_name,
            "argument_schema_valid": _schema_valid(name, arguments, by_name),
            "accepted_tool_action": _accepted(name, arguments, oracle[row["id"]]),
            "facade_active": activation[(mode, row["id"])]["active"] if variant == "canonical_facade" else False,
            "capability_id": activation[(mode, row["id"])]["capability_id"] if variant == "canonical_facade" else None,
        })
        observations.append(observed)

    aggregates: dict[str, Any] = {}
    for mode in MODES:
        aggregates[mode] = {}
        for variant in VARIANTS:
            rows = [item for item in observations if item["mode"] == mode and item["variant"] == variant]
            families = {}
            for family in ("application_launch", "software_management"):
                subset = [item for item in rows if item["family"] == family]
                families[family] = {
                    "accepted": sum(item["accepted_tool_action"] for item in subset),
                    "total": len(subset),
                    "rate": round(sum(item["accepted_tool_action"] for item in subset) / len(subset), 6),
                }
            argument_rows = [item for item in rows if item["call_count"] == 1 and item["candidate_membership_valid"]]
            aggregates[mode][variant] = {
                "accepted": sum(item["accepted_tool_action"] for item in rows),
                "total": len(rows),
                "accepted_rate": round(sum(item["accepted_tool_action"] for item in rows) / len(rows), 6),
                "families": families,
                "candidate_membership_violations": sum(
                    item["name"] is not None and not item["candidate_membership_valid"] for item in rows
                ),
                "argument_schema_validity": round(
                    sum(item["argument_schema_valid"] for item in argument_rows) / len(argument_rows), 6
                ) if argument_rows else 0.0,
                "text_only_count": sum(item["call_count"] == 0 for item in rows),
                "median_schema_bytes": statistics.median(item["prompt_schema_bytes"] for item in rows),
                "median_latency_ms": round(statistics.median(item["latency_ms"] for item in rows), 3),
            }
    result = {
        "schema": "marvin.tool-selection-v13-ab-result/1.0",
        "status": "complete_raw",
        "runner_freeze_sha256": _sha(RUNNER_FREEZE),
        "authorization_sha256": _sha(AUTHORIZATION),
        "holdout_freeze_sha256": _sha(HOLDOUT_FREEZE),
        "benchmark": benchmark,
        "preflight": preflight,
        "observations": observations,
        "aggregates": aggregates,
        "business_tool_execution_count": 0,
        "host_side_effect_count": 0,
        "product_activation_count": 0,
    }
    _atomic(RESULT, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    value = asyncio.run(run(preflight_only=args.preflight_only))
    print(json.dumps(value.get("preflight", value), ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
