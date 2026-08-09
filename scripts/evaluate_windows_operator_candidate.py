"""Évalue mécaniquement un candidat Windows Operator contre le contrat Forge v1.1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS = (ROOT / "benchmarks" / "windows-operator" / "campaigns").resolve()
POLICY = ROOT / "benchmarks" / "windows-operator" / "v1.1" / "acceptance-policy.json"


def _read(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Document JSON invalide : {path}")
    return data


def _campaign(path: str) -> tuple[Path, dict[str, Any]]:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    resolved = resolved.resolve()
    if CAMPAIGNS not in resolved.parents or resolved.suffix.casefold() != ".json":
        raise ValueError("Une preuve doit rester dans benchmarks/windows-operator/campaigns.")
    document = _read(resolved)
    if document.get("status") != "complete":
        raise ValueError(f"Campagne incomplète : {resolved.name}")
    return resolved, document


def _summary(document: dict[str, Any]) -> dict[str, Any]:
    summary = document.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("Résumé de campagne absent.")
    return summary


def _step_median(document: dict[str, Any]) -> float:
    results = document.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("Résultats de campagne absents.")
    return float(median(len(row.get("selected_tools") or []) for row in results))


def evaluate(
    *,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    holdout: dict[str, Any],
    routing_development: dict[str, Any],
    routing_holdout: dict[str, Any],
    functional_regressions: int,
    rollback_verified: bool,
) -> dict[str, Any]:
    if baseline.get("split") != "development" or candidate.get("split") != "development":
        raise ValueError("Baseline et candidat E2E doivent utiliser le split development.")
    if holdout.get("split") != "holdout" or routing_holdout.get("split") != "holdout":
        raise ValueError("Les preuves holdout doivent déclarer le split holdout.")
    identity = ("model", "model_digest", "scenario_corpus_sha256")
    if any(baseline.get(key) != candidate.get(key) for key in identity):
        raise ValueError("Le candidat E2E ne partage pas l'identité gelée de la baseline.")
    if any(candidate.get(key) != holdout.get(key) for key in ("model", "model_digest")):
        raise ValueError("Le holdout n'utilise pas le modèle exact du candidat.")
    if not candidate.get("source_hashes") or not holdout.get("source_hashes"):
        raise ValueError("Les preuves candidates doivent être liées aux sources.")

    base = _summary(baseline)
    dev = _summary(candidate)
    held = _summary(holdout)
    baseline_rate = float(base["success_rate"])
    candidate_rate = float(dev["success_rate"])
    holdout_rate = float(held["success_rate"])
    baseline_failure = 1.0 - baseline_rate
    candidate_failure = 1.0 - candidate_rate
    gain = candidate_rate - baseline_rate
    reduction = (
        (baseline_failure - candidate_failure) / baseline_failure
        if baseline_failure > 0
        else 0.0
    )
    false_successes = int(dev.get("false_success_count") or 0) + int(
        held.get("false_success_count") or 0
    )
    intelligence_regressions = int(
        holdout_rate < candidate_rate or holdout_rate < 0.85
    )
    rollback_rate = 1.0 if rollback_verified else 0.0
    generalized = all(
        (
            candidate_rate >= 0.85,
            gain >= 0.20 or reduction >= 0.50,
            false_successes == 0,
            functional_regressions == 0,
            intelligence_regressions == 0,
            rollback_rate == 1.0,
        )
    )

    baseline_steps = _step_median(baseline)
    candidate_steps = _step_median(candidate)
    step_ratio = candidate_steps / baseline_steps if baseline_steps else 1.0
    efficiency_met = step_ratio <= 0.75
    engineering_runs = int(dev["runs"]) + int(held["runs"])
    engineering_evidence_met = engineering_runs >= 75 and false_successes == 0
    general_release_evidence_met = engineering_runs >= 300 and false_successes == 0
    status = "rollback"
    if generalized and engineering_evidence_met:
        status = "engineering_accepted" if efficiency_met else "engineering_accepted_with_efficiency_debt"

    return {
        "schema": "marvin.windows-task-acceptance-report/1.0",
        "status": status,
        "outcome": {
            "generalized_contract_met": generalized,
            "engineering_evidence_met": engineering_evidence_met,
            "general_release_evidence_met": general_release_evidence_met,
            "general_release_blocker": (
                None if general_release_evidence_met else "300 exécutions réelles sans faux succès requises"
            ),
        },
        "metrics": {
            "baseline_success_rate": round(baseline_rate, 4),
            "candidate_success_rate": round(candidate_rate, 4),
            "holdout_success_rate": round(holdout_rate, 4),
            "success_rate_gain_points": round(gain, 4),
            "failure_rate_reduction": round(reduction, 4),
            "false_success_count": false_successes,
            "functional_regression_count": functional_regressions,
            "intelligence_regression_count": intelligence_regressions,
            "reversible_rollback_success_rate": rollback_rate,
            "redundant_confirmation_count": int(dev.get("redundant_confirmation_count") or 0)
            + int(held.get("redundant_confirmation_count") or 0),
            "engineering_live_runs": engineering_runs,
        },
        "efficiency": {
            "baseline_median_steps": baseline_steps,
            "candidate_median_steps": candidate_steps,
            "median_step_ratio": round(step_ratio, 4),
            "maximum_ratio": 0.75,
            "met": efficiency_met,
        },
        "routing_diagnostic": {
            "development": _summary(routing_development),
            "holdout": _summary(routing_holdout),
            "is_acceptance_metric": False,
        },
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-e2e", required=True)
    parser.add_argument("--candidate-e2e", required=True)
    parser.add_argument("--holdout-e2e", required=True)
    parser.add_argument("--routing-development", required=True)
    parser.add_argument("--routing-holdout", required=True)
    parser.add_argument("--functional-regressions", type=int, required=True)
    parser.add_argument("--rollback-verified", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.functional_regressions < 0:
        raise ValueError("Le nombre de régressions ne peut pas être négatif.")
    paths_and_documents = [
        _campaign(value)
        for value in (
            args.baseline_e2e,
            args.candidate_e2e,
            args.holdout_e2e,
            args.routing_development,
            args.routing_holdout,
        )
    ]
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output = output.resolve()
    if CAMPAIGNS not in output.parents or output.suffix.casefold() != ".json":
        raise ValueError("Le rapport doit rester dans le dossier des campagnes.")
    report = evaluate(
        baseline=paths_and_documents[0][1],
        candidate=paths_and_documents[1][1],
        holdout=paths_and_documents[2][1],
        routing_development=paths_and_documents[3][1],
        routing_holdout=paths_and_documents[4][1],
        functional_regressions=args.functional_regressions,
        rollback_verified=args.rollback_verified,
    )
    report["policy"] = {
        "path": str(POLICY.relative_to(ROOT)).replace("\\", "/"),
        "sha256": hashlib.sha256(POLICY.read_bytes()).hexdigest(),
    }
    report["evidence"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path, _document in paths_and_documents
    }
    _atomic_write(output, report)
    print(json.dumps({"output": str(output), "status": report["status"]}, ensure_ascii=False))
    return 0 if report["outcome"]["generalized_contract_met"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Évaluation Forge refusée : {exc}", file=sys.stderr)
        raise SystemExit(2)
