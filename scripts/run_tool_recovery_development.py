"""Produit la preuve reproductible du split developpement Forge v1.2."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

from forge_v12_oracle import evaluate_candidate_names
from tools import TOOLS_SPEC
from unknown_tool_resolver import resolve_unknown_tool


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    folder = ROOT / "benchmarks/tool-recovery/v1.2"
    policy_path = folder / "acceptance-policy.json"
    corpus_path = folder / "development-corpus.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    repetitions = int(policy["campaign"]["development_repetitions"])
    rows: list[dict] = []
    accepted = forbidden = implicit = 0
    for item in corpus["items"]:
        result = resolve_unknown_tool(item["unknown_name"], item["arguments"], TOOLS_SPEC)
        names = [candidate["name"] for candidate in result["rediscovery"]["candidates"]]
        verdict = evaluate_candidate_names(item, names)
        row_forbidden = sorted(set(names) & set(item["forbidden_tools"]))
        rows.append({
            "id": item["id"],
            "family": item["family"],
            "candidate_names": names,
            "accepted": verdict["accepted"],
            "forbidden_candidates": row_forbidden,
            "executed": result["executed"],
        })
        accepted += int(verdict["accepted"]) * repetitions
        forbidden += len(row_forbidden) * repetitions
        implicit += int(bool(result["executed"])) * repetitions
    total = len(rows) * repetitions
    source_paths = [
        policy_path,
        corpus_path,
        BACKEND / "unknown_tool_resolver.py",
        BACKEND / "capability_catalog.py",
        BACKEND / "tool_capability_ranking.py",
        ROOT / "scripts/forge_v12_oracle.py",
    ]
    report = {
        "schema": "marvin.tool-recovery-development-result/1.0",
        "scope": "development_only",
        "holdout_independent": False,
        "generalization_allowed": False,
        "repetitions": repetitions,
        "runs": total,
        "candidate_set_recall": round(accepted / total, 4),
        "false_replacement_count": forbidden,
        "implicit_execution_count": implicit,
        "valid_new_native_call_rate": None,
        "business_outcome_success_rate": None,
        "unmeasured_metrics_reason": "Aucun holdout LLM et aucun parcours metier independant n'ont encore ete executes.",
        "source_hashes": {
            str(path.relative_to(ROOT)).replace("\\", "/"): _hash(path)
            for path in source_paths
        },
        "items": rows,
    }
    output = folder / "development-results.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "runs", "candidate_set_recall", "false_replacement_count",
        "implicit_execution_count", "generalization_allowed",
    )}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
