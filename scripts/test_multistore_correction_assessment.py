"""Vérifie la supersession TD-014 sans transformer une preuve produit en E7."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "benchmarks" / "tool-evidence"
PREREG = EVIDENCE / "v1.5" / "multistore-correction-preregistration.json"
SUPERSESSION = EVIDENCE / "v1.5" / "direct-surface-supersession.json"
ASSESSMENT = EVIDENCE / "v1.5" / "multistore-correction-assessment.json"
V1_CONTRACTS = EVIDENCE / "v1.1" / "direct-fixture-contracts.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _blob(commit: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"Blob produit introuvable : {relative_path}")
    return result.stdout


def main() -> int:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    supersession = json.loads(SUPERSESSION.read_text(encoding="utf-8"))
    assessment = json.loads(ASSESSMENT.read_text(encoding="utf-8"))
    frozen = json.loads(V1_CONTRACTS.read_text(encoding="utf-8"))

    assert assessment["preregistration_sha256"] == _sha256(PREREG)
    assert assessment["supersession_sha256"] == _sha256(SUPERSESSION)
    assert prereg["contract_supersession_authorized_after_validation"] is True
    assert supersession["tool_execution_performed"] is False
    assert supersession["fixture_execution_performed"] is False
    assert supersession["e7_verification_granted"] is False
    assert assessment["e7_verification_granted"] is False
    assert assessment["source_result_modified"] is False

    commit = assessment["product_source_commit"]
    assert commit == supersession["product_source_commit"]
    for relative_path, expected in assessment["product_source_sha256"].items():
        assert hashlib.sha256(_blob(commit, relative_path)).hexdigest() == expected
    for relative_path, expected in assessment["test_source_sha256"].items():
        path = ROOT / relative_path
        if relative_path == "scripts/test_td014_action_surfaces.py":
            assert _sha256(path) == expected
        else:
            assert hashlib.sha256(_blob(commit, relative_path)).hexdigest() == expected

    previous = {row["id"]: row for row in frozen["contracts"]}
    changed = {row["contract_id"]: row for row in supersession["superseded_contracts"]}
    retained = {row["contract_id"]: row for row in supersession["retained_contracts"]}
    assert set(changed) == {
        "direct-note_delete---default--",
        "direct-memory_delete---default--",
        "direct-code_workspace_control-resume",
    }
    assert set(retained) == {
        "direct-code_workspace_control-cancel",
        "direct-vm_lab_install-status",
    }
    for contract_id, row in {**changed, **retained}.items():
        assert row["class"] == previous[contract_id]["class"]
    assert set(changed["direct-note_delete---default--"]["stores"]) == {"sqlite", "qdrant"}
    assert set(changed["direct-memory_delete---default--"]["stores"]) == {
        "sqlite", "qdrant", "memory_mesh"
    }
    assert "network" in changed["direct-code_workspace_control-resume"]["stores"]
    assert retained["direct-code_workspace_control-cancel"]["v1_4_finding"] == (
        "SUPERSEDED_STATIC_FALSE_POSITIVE"
    )
    assert retained["direct-vm_lab_install-status"]["class"] == "N"
    assert supersession["remaining_scope"]["static_unknowns_not_converted_to_absent"] == 17
    assert all(row["e7_state"] == "UNVERIFIED" for row in assessment["cases"])
    assert assessment["limits"]["no_security_register_entry_promoted"] is True
    assert assessment["rollback"]["persistent_data_migration"] is False

    print(
        "TD-014 Assessment OK - 3 surfaces supersédées, 2 contrats retenus, "
        "zéro promotion E7."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
