"""Vérifie l'inventaire E7 publié sans relancer ni importer le backend."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.3"
RESULT = BASE / "direct-surface-analysis.json"
EXPECTED_RESULT_SHA256 = "2b50334d8c82e53f73b614da0b29e9501534ad00831932243412d9525c8fabb4"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    assert sha256(RESULT) == EXPECTED_RESULT_SHA256
    report = json.loads(RESULT.read_text(encoding="utf-8"))
    assert report["status"] == "static_analysis_published_contracts_unchanged"
    assert report["tool_execution_performed"] is False
    assert report["contract_mutation_performed"] is False
    assert report["contracts"] == 22
    assert sum(report["counts"].values()) == 22
    assert report["contracts_sha256"] == sha256(
        ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "direct-fixture-contracts.json"
    )
    assert report["policy_sha256"] == sha256(BASE / "surface-analysis-preregistration.json")
    assert report["rules_sha256"] == sha256(BASE / "surface-analysis-rules.json")
    assert report["analyzer_sha256"] == sha256(ROOT / "scripts" / "e7_surface_analyzer.py")
    note = next(item for item in report["results"] if item["tool"] == "note_delete")
    assert note["state"] == "UNDER_DECLARED"
    assert set(note["confirmed_effects"]) == {"sqlite", "qdrant"}
    assert note["unknown"] is False
    assert all(item["state"] in {"CONFIRMED", "UNDER_DECLARED", "UNKNOWN", "OVER_DECLARED"} for item in report["results"])
    assert "static_analysis_does_not_prove_runtime_branch_coverage" in report["limitations"]
    print(f"E7 Surface Analysis Result OK - 22 contracts | {report['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
