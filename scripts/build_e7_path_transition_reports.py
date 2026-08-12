from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.4"
V13 = ROOT / "benchmarks" / "tool-evidence" / "v1.3" / "direct-surface-analysis.json"
V14 = BASE / "direct-path-surface-analysis.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    old = json.loads(V13.read_text(encoding="utf-8"))
    new = json.loads(V14.read_text(encoding="utf-8"))
    old_by_id = {item["contract_id"]: item for item in old["results"]}
    new_by_id = {item["contract_id"]: item for item in new["results"]}
    assert old_by_id.keys() == new_by_id.keys()
    transitions = []
    for contract_id in sorted(old_by_id):
        previous, current = old_by_id[contract_id], new_by_id[contract_id]
        transitions.append({
            "contract_id": contract_id,
            "v1_3_state": previous["state"],
            "v1_4_state": current["state"],
            "changed": previous["state"] != current["state"],
            "compatible_evidence_total": current["compatible_effects"]["total"],
            "guarded_evidence_total": current["guarded_effects"]["total"],
            "unresolved_evidence_total": current["unresolved_paths"]["total"],
            "evidence_sha256": {
                "compatible": current["compatible_effects"]["sha256"],
                "guarded": current["guarded_effects"]["sha256"],
                "unresolved": current["unresolved_paths"]["sha256"],
            },
            "reason": "path_sensitive_reanalysis_with_explicit_scenario_constraints",
        })
    old_unknown = sorted(item["contract_id"] for item in old["results"] if item["state"] == "UNKNOWN")
    report = {
        "schema": "marvin.e7-v1.3-v1.4-transition-report/1.0",
        "status": "published_after_v1_4_result",
        "v1_3_sha256": digest(V13),
        "v1_4_sha256": digest(V14),
        "contracts": len(transitions),
        "v1_3_unknown_contracts": old_unknown,
        "v1_3_unknown_contracts_accounted_for": len(old_unknown),
        "silent_transitions": 0,
        "transitions": transitions,
    }
    (BASE / "v1.3-v1.4-transition-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    retrospective_ids = {
        "known_multistore_delete": "direct-note_delete---default--",
        "known_preview_with_early_return": "direct-bulk_rename-preview",
        "known_status_with_reconciliation": "direct-vm_lab_install-status",
    }
    checks = {label: new_by_id[contract_id] for label, contract_id in retrospective_ids.items()}
    retrospective = {
        "schema": "marvin.e7-path-analysis-retrospective-check/1.0",
        "status": "evaluated_after_v1_4_publication_without_rule_change",
        "v1_4_sha256": digest(V14),
        "analyzer_special_cases_forbidden": True,
        "checks": {
            "known_multistore_delete": {
                "state": checks["known_multistore_delete"]["state"],
                "effects": checks["known_multistore_delete"]["compatible_effects"],
            },
            "known_preview_with_early_return": {
                "state": checks["known_preview_with_early_return"]["state"],
                "compatible_mutations": checks["known_preview_with_early_return"]["compatible_effects"],
                "interpretation": "no_compatible_mutation_static_unknown_remains_and_prior_e7_runtime_certification_is_not_superseded",
            },
            "known_status_with_reconciliation": {
                "state": checks["known_status_with_reconciliation"]["state"],
                "effects": checks["known_status_with_reconciliation"]["compatible_effects"],
                "required_write_target": "os.replace",
            },
        },
    }
    (BASE / "retrospective-known-case-check.json").write_text(
        json.dumps(retrospective, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"E7 Path Transition Reports - {len(transitions)} contracts, {len(old_unknown)} prior UNKNOWN accounted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
