"""Validate the frozen v1.4 holdout without executing any business tool."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from qdrant_client import QdrantClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

import agent_prompt
import agent_tool_selection as selection
import database as db
import run_tool_selection_ablation as stage_a
import run_tool_selection_stage_b as shared
import tool_router
from config import QDRANT_PATH


BASE = ROOT / "benchmarks/tool-selection/v1.4"
CORPUS = BASE / "holdout-corpus.json"
ORACLE = BASE / "holdout-oracle.json"
HOLDOUT_FREEZE = BASE / "holdout-freeze-manifest.json"
RUNNER_FREEZE = BASE / "validation-runner-freeze.json"
AUTHORIZATION = BASE / "validation-authorization.json"
RESULT = BASE / "validation-result.json"
MODES = {"eco": 18, "balanced": 40, "performance": 80, "max": 250}
FIXED_NOW = datetime(2026, 8, 15, 12, 0, 0)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _candidate_accepts(
    names: set[str],
    accepted_calls: list[dict[str, Any]],
) -> bool:
    return any(str(call.get("tool") or "") in names for call in accepted_calls)


def _stability(rows: list[dict[str, Any]]) -> float:
    grouped: dict[str, list[tuple[str | None, bytes]]] = {}
    for row in rows:
        grouped.setdefault(row["id"], []).append(
            (row["name"], _canonical(row["arguments"]))
        )
    stable = sum(len(set(values)) == 1 for values in grouped.values())
    return stable / len(grouped) if grouped else 0.0


async def _views(corpus: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    records = [{"id": row["id"], "query": row["prompt"]} for row in corpus]
    client = QdrantClient(path=QDRANT_PATH)
    try:
        collections = {item.name for item in client.get_collections().collections}
        if tool_router._TOOL_COLLECTION not in collections:
            raise RuntimeError("Index sémantique des outils absent.")
        expected_hash = tool_router.tool_index_fingerprint(selection.TOOLS_SPEC)
        if db.get_setting("tool_index_hash") != expected_hash:
            raise RuntimeError("Index sémantique des outils périmé.")
        lexical, semantic, _metadata = await stage_a._signals(
            records,
            client,
            batch_size=16,
            control_query_count=5,
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
                specification
                for specification in selection.TOOLS_SPEC
                if specification["function"]["name"] in names
            ]
    return output


async def run(*, preflight_only: bool) -> dict[str, Any]:
    freeze = json.loads(HOLDOUT_FREEZE.read_text(encoding="utf-8"))
    for relative, expected in freeze["files"].items():
        assert _sha(ROOT / relative) == expected, relative
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))["items"]
    oracle = {
        row["id"]: row["accepted_calls"]
        for row in json.loads(ORACLE.read_text(encoding="utf-8"))["items"]
    }
    views = await _views(corpus)
    candidate_rows: list[dict[str, Any]] = []
    for mode, budget in MODES.items():
        for row in corpus:
            specs = views[(mode, row["id"])]
            names = {str(item["function"]["name"]) for item in specs}
            candidate_rows.append({
                "id": row["id"],
                "family": row["family"],
                "mode": mode,
                "budget": budget,
                "candidate_count": len(specs),
                "accepted_candidate_present": _candidate_accepts(names, oracle[row["id"]]),
                "candidate_names_sha256": hashlib.sha256(_canonical(sorted(names))).hexdigest(),
            })
    preflight = {
        "status": "preflight_complete",
        "holdout_count": len(corpus),
        "modes": MODES,
        "candidate_rows": len(candidate_rows),
        "candidate_recall": {
            mode: round(
                sum(row["accepted_candidate_present"] for row in candidate_rows if row["mode"] == mode)
                / len(corpus),
                6,
            )
            for mode in MODES
        },
        "family_candidate_recall": {
            mode: {
                family: round(
                    sum(
                        row["accepted_candidate_present"]
                        for row in candidate_rows
                        if row["mode"] == mode and row["family"] == family
                    )
                    / sum(row["mode"] == mode and row["family"] == family for row in candidate_rows),
                    6,
                )
                for family in sorted({row["family"] for row in corpus})
            }
            for mode in MODES
        },
        "business_tool_execution_count": 0,
        "host_side_effect_count": 0,
        "benchmark_model_call_count": 0,
    }
    if preflight_only:
        return preflight

    runner = json.loads(RUNNER_FREEZE.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    if RESULT.exists():
        raise RuntimeError("Résultat v1.4 déjà publié; autorisation consommée.")
    for relative, expected in runner["frozen_hashes"].items():
        assert _sha(ROOT / relative) == expected, relative
    assert authorization["runner_freeze_sha256"] == _sha(RUNNER_FREEZE)
    assert authorization["benchmark_model_calls"] is True
    assert authorization["business_tool_execution"] is False

    benchmark = runner["benchmark"]
    system_prompt = agent_prompt.build_system_prompt([], 2, now=FIXED_NOW, compact=False)
    tasks: list[Any] = []
    descriptors: list[tuple[dict[str, Any], str, int, list[dict[str, Any]]]] = []
    async with httpx.AsyncClient(timeout=600, trust_env=False) as client:
        tags = (await client.get(f"{shared.OLLAMA}/api/tags")).json().get("models") or []
        model_row = next((row for row in tags if row.get("name") == benchmark["model"]), None)
        if not model_row or model_row.get("digest") != benchmark["digest"] or not model_row.get("remote_host"):
            raise RuntimeError("Provenance du modèle benchmark invalide.")
        semaphore = asyncio.Semaphore(int(runner["concurrency_maximum"]))
        for row in corpus:
            for mode in MODES:
                specs = views[(mode, row["id"])]
                for repetition in range(1, int(runner["repetitions_per_intent"]) + 1):
                    descriptors.append((row, mode, repetition, specs))
                    tasks.append(shared._benchmark_call(
                        client,
                        semaphore,
                        model=benchmark["model"],
                        system_prompt=system_prompt,
                        prompt=row["prompt"],
                        tools=specs,
                        options={
                            "temperature": 0.1,
                            "top_p": 0.9,
                            "seed": int(runner["seed"]),
                            "num_predict": 512,
                        },
                    ))
        raw = await asyncio.gather(*tasks)

    observations: list[dict[str, Any]] = []
    for descriptor, observed in zip(descriptors, raw, strict=True):
        row, mode, repetition, specs = descriptor
        by_name = {str(item["function"]["name"]): item for item in specs}
        name, arguments = observed["name"], observed["arguments"]
        observed.update({
            "id": row["id"],
            "family": row["family"],
            "mode": mode,
            "repetition": repetition,
            "candidate_count": len(specs),
            "candidate_membership_valid": name is None or name in by_name,
            "argument_schema_valid": shared._schema_valid(name, arguments, by_name),
            "accepted_tool_action": shared._accepted(name, arguments, oracle[row["id"]]),
        })
        observations.append(observed)

    aggregates: dict[str, Any] = {}
    for mode in MODES:
        rows = [row for row in observations if row["mode"] == mode]
        called = [row for row in rows if row["call_count"] == 1 and row["candidate_membership_valid"]]
        family_rows = {
            family: [row for row in rows if row["family"] == family]
            for family in sorted({row["family"] for row in corpus})
        }
        aggregates[mode] = {
            "accepted": sum(row["accepted_tool_action"] for row in rows),
            "total": len(rows),
            "accepted_rate": round(sum(row["accepted_tool_action"] for row in rows) / len(rows), 6),
            "families": {
                family: {
                    "accepted": sum(row["accepted_tool_action"] for row in subset),
                    "total": len(subset),
                    "rate": round(sum(row["accepted_tool_action"] for row in subset) / len(subset), 6),
                }
                for family, subset in family_rows.items()
            },
            "repeat_stability": round(_stability(rows), 6),
            "candidate_membership_violations": sum(
                row["name"] is not None and not row["candidate_membership_valid"] for row in rows
            ),
            "argument_schema_validity": round(
                sum(row["argument_schema_valid"] for row in called) / len(called), 6
            ) if called else 0.0,
            "text_only_count": sum(row["call_count"] == 0 for row in rows),
            "median_candidate_count": statistics.median(row["candidate_count"] for row in rows),
            "median_latency_ms": round(statistics.median(row["latency_ms"] for row in rows), 3),
            "observed_names": dict(Counter(str(row["name"]) for row in rows)),
        }
    result = {
        "schema": "marvin.tool-selection-v14-validation-result/1.0",
        "status": "complete_raw",
        "source_commit": runner["product_commit"],
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
    shared.atomic(RESULT, result)
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
