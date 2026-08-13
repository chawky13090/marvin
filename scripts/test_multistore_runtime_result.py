"""Vérifie le résultat runtime TD-014 sans lui accorder une preuve E7."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.5"
RESULT = BASE / "multistore-correction-runtime-result-v1.2.json"
ERRATUM = BASE / "multistore-correction-assessment-erratum-v1.1.json"


def main() -> int:
    value = json.loads(RESULT.read_text(encoding="utf-8"))
    assert value["status"] == "product_runtime_validated_e7_unverified"
    assert value["erratum_sha256"] == hashlib.sha256(ERRATUM.read_bytes()).hexdigest()
    assert value["prior_failed_observation_preserved"] is True
    commit = value["runtime_commit"]
    assert subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        check=False,
    ).returncode == 0
    runtime = value["runtime"]
    assert runtime["version"] == "2.648.0" and runtime["state"] == "ready"
    assert runtime["tools"] == 364
    assert all(runtime["dependencies"].values())
    gate = value["full_gate"]
    assert gate == {
        "expected_stages": 312,
        "executed_stages": 308,
        "skipped_live_stages": 4,
        "failed": 0,
        "success": True,
        "duration_seconds": 629.0,
        "build_included": True,
    }
    fixture = value["fixture_result"]
    assert fixture["fixture_user_data"] is False
    assert fixture["fixture_cleanup_verified"] is True
    assert fixture["note_create_consistency"] == "complete"
    assert fixture["note_update_consistency"] == "complete"
    assert fixture["note_delete_without_confirmation_status"] == 409
    assert fixture["note_delete_confirmed"] is True
    assert fixture["memory_create_consistency"] == "complete"
    assert fixture["memory_delete_confirmed"] is True
    assert fixture["vm_status_reads"] == 5
    assert fixture["vm_state_sha256_unchanged"] is True
    assert value["live_smokes"] == {
        "api": "28/28",
        "pages": "41/41",
        "chat": "5/5",
        "voice_max_concurrency": 1,
        "all_passed": True,
        "executed_sequentially": True,
    }
    interpretation = value["interpretation"]
    assert interpretation["product_correction_validated"] is True
    assert interpretation["e7_verification_granted"] is False
    assert interpretation["security_register_entry_promoted"] is False
    assert interpretation["static_unknowns_converted_to_absent"] == 0
    assert value["rollback"]["persistent_data_migration"] is False
    print("TD-014 Runtime Result OK - produit validé, fixtures nettoyées, E7 non promu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
