"""Measure deterministic K/L/S contribution on the non-release v1.5 dev corpus."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from qdrant_client import QdrantClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

import database as db
import run_tool_selection_ablation as stage_a
import tool_router
from config import QDRANT_PATH


BASE = ROOT / "benchmarks/tool-selection/v1.5"
CORPUS = BASE / "development-corpus.json"
RESULT = BASE / "development-stage-a-result.json"
MODES = {"eco": 18, "balanced": 40, "performance": 80, "max": 250}
CONFIGURATIONS = ("K", "L", "S", "K+L", "K+S", "L+S", "K+L+S")
MUTATIONS = {"winget_install", "winget_upgrade", "winget_uninstall"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic(path: Path, payload: dict) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


async def run() -> dict:
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    items = payload["items"]
    records = [{"id": item["id"], "query": item["prompt"]} for item in items]
    accepted = {item["id"]: set(item["accepted"]) for item in items}
    intents = {item["id"]: item["intent"] for item in items}

    client = QdrantClient(path=QDRANT_PATH)
    try:
        collections = {item.name for item in client.get_collections().collections}
        if tool_router._TOOL_COLLECTION not in collections:
            raise RuntimeError("Index sémantique des outils absent.")
        lexical, semantic, metadata = await stage_a._signals(
            records, client, batch_size=16, control_query_count=5
        )
    finally:
        client.close()
    matrix, costs = await stage_a._candidate_matrix(
        records, modes=MODES, lexical_cache=lexical, semantic_cache=semantic
    )

    rows = []
    for mode in MODES:
        for configuration in CONFIGURATIONS:
            for item in items:
                names = matrix[mode][configuration][item["id"]]
                intent = intents[item["id"]]
                forbidden_mutation = bool(names & MUTATIONS) and intent in {
                    "software.search", "software.inventory", "software.updates_check",
                    "software.manual_panel", "software.ambiguous",
                }
                rows.append({
                    "id": item["id"],
                    "intent": intent,
                    "mode": mode,
                    "configuration": configuration,
                    "accepted_present": bool(names & accepted[item["id"]]),
                    "forbidden_mutation_present": forbidden_mutation,
                    "candidate_count": len(names),
                    "candidate_names_sha256": hashlib.sha256(
                        json.dumps(sorted(names), separators=(",", ":")).encode("utf-8")
                    ).hexdigest(),
                    "duration_ms": costs[mode][configuration][item["id"]]["duration_ms"],
                })

    summaries = {}
    for mode in MODES:
        summaries[mode] = {}
        for configuration in CONFIGURATIONS:
            selected = [row for row in rows if row["mode"] == mode and row["configuration"] == configuration]
            summaries[mode][configuration] = {
                "candidate_recall": round(sum(row["accepted_present"] for row in selected) / len(selected), 6),
                "forbidden_mutation_count": sum(row["forbidden_mutation_present"] for row in selected),
                "per_intent_recall": {
                    intent: round(
                        sum(row["accepted_present"] for row in selected if row["intent"] == intent)
                        / sum(row["intent"] == intent for row in selected), 6
                    )
                    for intent in sorted(set(intents.values()))
                },
            }
    result = {
        "schema": "marvin.software-intent-development-stage-a-result/1.0",
        "status": "development_evidence_not_release_validation",
        "product_version": "2.662.0",
        "product_source_sha256": _sha(BACKEND / "agent_tool_selection.py"),
        "preregistration_sha256": _sha(BASE / "software-intent-boundary-preregistration.json"),
        "corpus_sha256": _sha(CORPUS),
        "corpus_count": len(items),
        "modes": MODES,
        "configurations": list(CONFIGURATIONS),
        "summaries": summaries,
        "signal_metadata": metadata,
        "business_tool_execution_count": 0,
        "host_side_effect_count": 0,
        "benchmark_model_call_count": 0,
        "limitations": [
            "development corpus authored from public contracts after the defect class was known",
            "not usable for release or generalization claims",
            "Stage A measures candidate composition, not final model choice",
        ],
    }
    _atomic(RESULT, result)
    return result


def main() -> int:
    result = asyncio.run(run())
    print(json.dumps(result["summaries"], ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
