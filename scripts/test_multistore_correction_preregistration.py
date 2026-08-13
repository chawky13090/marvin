"""Verrouille les prédicats TD-014 avant toute correction produit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks" / "tool-evidence" / "v1.5" / "multistore-correction-preregistration.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _blob(source_commit: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{source_commit}:{relative_path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"Source gelée introuvable : {relative_path}")
    return result.stdout


def main() -> int:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["status"] == "frozen_before_product_change"
    assert policy["tool_execution_authorized"] is False
    assert policy["fixture_execution_authorized"] is False
    assert policy["product_change_authorized"] is True
    assert policy["historical_artifacts_must_remain_immutable"] is True

    for relative_path, expected in policy["baseline_sha256"].items():
        assert _sha256(ROOT / relative_path) == expected, relative_path
    for relative_path, expected in policy["governed_product_sources"].items():
        assert hashlib.sha256(_blob(policy["source_commit"], relative_path)).hexdigest() == expected

    invariants = policy["general_invariants"]
    assert all(invariants.values())
    cases = {item["contract_id"]: item for item in policy["cases"]}
    assert set(cases) == {
        "direct-note_delete---default--",
        "direct-memory_delete---default--",
        "direct-code_workspace_control-resume",
        "direct-code_workspace_control-cancel",
        "direct-vm_lab_install-status",
    }
    assert cases["direct-code_workspace_control-cancel"]["source_audit"] == "candidate_static_false_positive"
    assert cases["direct-vm_lab_install-status"]["required_effects"] == []
    assert set(cases["direct-memory_delete---default--"]["required_effects"]) == {
        "sqlite", "qdrant", "filesystem"
    }

    validation = policy["validation_requirements"]
    assert validation["negative_failure_injection_per_mutated_store"] is True
    assert validation["compensation_failure_test"] is True
    assert validation["cold_restart_and_live_smoke_required"] is True
    assert policy["logging_decision"]["note_or_memory_content_in_logs_forbidden"] is True
    assert policy["rollback"]["persistent_schema_change"] is False
    print("TD-014 Preregistration OK - 5 constats, prédicats gelés, zéro exécution métier.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
