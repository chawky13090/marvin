"""Tests déterministes de la décision d'acceptation Windows Operator."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "windows_acceptance", ROOT / "scripts" / "evaluate_windows_operator_candidate.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _campaign(split: str, success: float, runs: int, *, source: bool = True) -> dict:
    passed = int(success * runs)
    document = {
        "status": "complete",
        "split": split,
        "model": "model:cloud",
        "model_digest": "a" * 64,
        "scenario_corpus_sha256": "b" * 64,
        "results": [{"selected_tools": ["windows_task"]} for _ in range(runs)],
        "summary": {
            "runs": runs,
            "passed": passed,
            "failed": runs - passed,
            "success_rate": success,
            "false_success_count": 0,
            "redundant_confirmation_count": 0,
        },
    }
    if source:
        document["source_hashes"] = {"agent.py": "c" * 64}
    return document


def main() -> int:
    baseline = _campaign("development", 0.80, 50, source=False)
    baseline["results"] = [
        {"selected_tools": ["tool_search", "legacy", "oracle"]} for _ in range(50)
    ]
    candidate = _campaign("development", 0.90, 50)
    holdout = _campaign("holdout", 1.0, 25)
    routing_dev = _campaign("development", 0.55, 240)
    routing_holdout = _campaign("holdout", 0.48, 120)
    accepted = MODULE.evaluate(
        baseline=baseline,
        candidate=candidate,
        holdout=holdout,
        routing_development=routing_dev,
        routing_holdout=routing_holdout,
        functional_regressions=0,
        rollback_verified=True,
    )
    assert accepted["status"] == "engineering_accepted"
    assert accepted["metrics"]["failure_rate_reduction"] == 0.5
    assert accepted["outcome"]["general_release_evidence_met"] is False

    candidate["summary"]["false_success_count"] = 1
    refused = MODULE.evaluate(
        baseline=baseline,
        candidate=candidate,
        holdout=holdout,
        routing_development=routing_dev,
        routing_holdout=routing_holdout,
        functional_regressions=0,
        rollback_verified=True,
    )
    assert refused["status"] == "rollback"
    assert refused["outcome"]["generalized_contract_met"] is False
    print("Windows operator acceptance OK - seuils, holdout et faux succès vérifiés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
