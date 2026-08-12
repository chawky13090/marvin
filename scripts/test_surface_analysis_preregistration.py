"""Valide le pré-enregistrement immuable de l'analyse des surfaces E7."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks" / "tool-evidence" / "v1.3" / "surface-analysis-preregistration.json"
RULES = ROOT / "benchmarks" / "tool-evidence" / "v1.3" / "surface-analysis-rules.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    scope = policy["scope"]
    assert scope["contracts"] == 22
    assert scope["tool_execution_authorized"] is False
    assert scope["contract_mutation_authorized"] is False
    assert scope["persistent_data_mutation_authorized"] is False
    rules = policy["analysis_contract"]
    assert rules["resolve_transitive_calls"] is True
    assert rules["resolve_function_local_imports"] is True
    assert rules["dynamic_or_unresolved_effectful_calls_produce_unknown"] is True
    assert rules["unknown_never_means_absent"] is True
    assert policy["canaries"]["ambiguous"]["expected_state"] == "UNKNOWN"
    truth = policy["known_truth_acceptance"]
    assert truth["tool"] == "note_delete"
    assert truth["expected_state"] == "UNDER_DECLARED"
    assert set(truth["expected_confirmed_effects"]) == {"sqlite", "qdrant"}
    assert truth["special_case_in_analyzer_forbidden"] is True
    for relative, expected in policy["frozen_source_sha256"].items():
        path = ROOT / relative
        assert path.is_file(), relative
        assert sha256(path) == expected, relative
    contracts = json.loads((ROOT / scope["source"]).read_text(encoding="utf-8"))["contracts"]
    assert len(contracts) == 22
    assert any(item["tool"] == "note_delete" for item in contracts)
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    assert set(rules["declared_surface_effects"]["database_scope"]) == {"sqlite"}
    assert rules["unknown_rules"]["dynamic_import"] is True
    assert rules["unknown_rules"]["unresolved_project_call"] is True
    assert "note_delete" not in RULES.read_text(encoding="utf-8")
    assert len(rules["sink_rules"]) >= 10
    assert rules["invariants"]["matched_sink_is_a_terminal_semantic_boundary"] is True
    print("E7 Surface Analysis Preregistration OK - 22 contracts, execution locked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
