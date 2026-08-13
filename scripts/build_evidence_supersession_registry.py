"""Publie l'inventaire E0-E7 courant et son registre de supersession."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidence_supersession import sha256, validate_registry
from tool_evidence_inventory import DEFAULT_ACTION, ROOT, build_inventory


POLICY = ROOT / "benchmarks" / "evidence-governance" / "v1" / "supersession-preregistration.json"
REGISTRY = ROOT / "benchmarks" / "evidence-governance" / "v1" / "supersession-registry.json"
INVENTORY = ROOT / "benchmarks" / "tool-evidence" / "v1.2" / "inventory.json"
PREVIEW = ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "e7-preview-execution-result.json"
APPLY = ROOT / "benchmarks" / "tool-evidence" / "v1.2" / "e7-apply-replay-result.json"
ANALYSIS_V13 = ROOT / "benchmarks" / "tool-evidence" / "v1.3" / "direct-surface-analysis.json"
ANALYSIS_V14 = ROOT / "benchmarks" / "tool-evidence" / "v1.4" / "direct-path-surface-analysis.json"
SURFACE_V15 = ROOT / "benchmarks" / "tool-evidence" / "v1.5" / "direct-surface-supersession.json"
PREREGISTRATION_COMMIT = "6627e64a411bdeb68b1c7232a44e41b3e11c5d30"


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _git_blob_matches(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    completed = subprocess.run(
        ["git", "show", f"{PREREGISTRATION_COMMIT}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0 and completed.stdout == path.read_bytes()


def _validate_e7_results() -> dict[tuple[str, str], dict[str, Any]]:
    preview = json.loads(PREVIEW.read_text(encoding="utf-8"))
    if not (
        preview.get("status") == "verified"
        and preview.get("contract") == "bulk_rename:preview"
        and preview.get("observable_mutation_count") == 0
        and preview.get("snapshots_identical") is True
    ):
        raise RuntimeError("La preuve E7 preview n'est pas terminale et explicite")
    apply = json.loads(APPLY.read_text(encoding="utf-8"))
    cycles = apply.get("cycles") or []
    if not (
        apply.get("final_verdict") == "R_CONFIRMED"
        and apply.get("cycles_required") == apply.get("cycles_completed") == 5
        and apply.get("normalized_cycles_identical") is True
        and len(cycles) == 5
        and all(cycle.get("exact_identity_restored") is True for cycle in cycles)
    ):
        raise RuntimeError("La preuve E7 apply n'est pas terminale et explicite")
    return {
        ("bulk_rename", "preview"): {
            "artifact": PREVIEW.relative_to(ROOT).as_posix(),
            "sha256": sha256(PREVIEW),
            "verdict": "N_CONFIRMED",
        },
        ("bulk_rename", "apply"): {
            "artifact": APPLY.relative_to(ROOT).as_posix(),
            "sha256": sha256(APPLY),
            "verdict": "R_CONFIRMED",
        },
    }


def _artifact(path: Path, selector: dict[str, str] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}
    if selector:
        value["selector"] = selector
    return value


def _revision(
    identifier: str,
    path: Path,
    state: str,
    *,
    successor: str | None = None,
    selector: dict[str, str] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {"id": identifier, "state": state, "artifact": _artifact(path, selector)}
    if successor:
        value["successor"] = successor
    return value


def _selector(collection: str, contract_id: str) -> dict[str, str]:
    return {"collection": collection, "key": "contract_id", "value": contract_id}


def build_registry() -> dict[str, Any]:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    allowed = set(policy["authorized_outputs"])
    if {REGISTRY.relative_to(ROOT).as_posix(), INVENTORY.relative_to(ROOT).as_posix()} != allowed:
        raise RuntimeError("Les sorties ne correspondent pas au pre-enregistrement")
    historical = [
        ROOT / "benchmarks" / "tool-evidence" / "v1" / "inventory.json",
        ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "inventory.json",
        ANALYSIS_V13,
        ANALYSIS_V14,
        SURFACE_V15,
        PREVIEW,
        APPLY,
    ]
    if not all(_git_blob_matches(path) for path in historical):
        raise RuntimeError("Une preuve historique differe du blob gele au pre-enregistrement")
    explicit_e7 = _validate_e7_results()
    inventory = build_inventory(
        ROOT / "data" / "secretary.db",
        explicit_e7=explicit_e7,
        schema_version="1.2",
    )
    inventory["governance"] = {
        "status": "current_terminal_evidence_only",
        "preregistration": POLICY.relative_to(ROOT).as_posix(),
        "preregistration_sha256": sha256(POLICY),
        "preregistration_commit": PREREGISTRATION_COMMIT,
        "historical_inventory_superseded": [
            "benchmarks/tool-evidence/v1/inventory.json",
            "benchmarks/tool-evidence/v1.1/inventory.json",
        ],
    }
    _write_atomic(INVENTORY, inventory)

    result_v14 = json.loads(ANALYSIS_V14.read_text(encoding="utf-8"))["results"]
    contract_ids = [str(row["contract_id"]) for row in result_v14]
    changed = {
        "direct-note_delete---default--": "superseded_contracts",
        "direct-memory_delete---default--": "superseded_contracts",
        "direct-code_workspace_control-resume": "superseded_contracts",
        "direct-code_workspace_control-cancel": "retained_contracts",
        "direct-vm_lab_install-status": "retained_contracts",
    }
    subjects: list[dict[str, Any]] = [
        {
            "subject": "tool_evidence_inventory:global",
            "revisions": [
                _revision("inventory-v1", historical[0], "superseded", successor="inventory-v1.1"),
                _revision("inventory-v1.1", historical[1], "superseded", successor="inventory-v1.2"),
                _revision("inventory-v1.2", INVENTORY, "current"),
            ],
        }
    ]
    for contract_id in contract_ids:
        revisions = [
            _revision(
                "surface-v1.3",
                ANALYSIS_V13,
                "superseded",
                successor="surface-v1.4",
                selector=_selector("results", contract_id),
            )
        ]
        if contract_id in changed:
            revisions.append(
                _revision(
                    "surface-v1.4",
                    ANALYSIS_V14,
                    "superseded",
                    successor="surface-v1.5",
                    selector=_selector("results", contract_id),
                )
            )
            revisions.append(
                _revision(
                    "surface-v1.5",
                    SURFACE_V15,
                    "current",
                    selector=_selector(changed[contract_id], contract_id),
                )
            )
        else:
            revisions.append(
                _revision(
                    "surface-v1.4",
                    ANALYSIS_V14,
                    "current",
                    selector=_selector("results", contract_id),
                )
            )
        subjects.append({"subject": f"e7_direct_surface_contract:{contract_id}", "revisions": revisions})
    subjects.extend(
        [
            {
                "subject": "e7_runtime_verdict:bulk_rename:preview",
                "revisions": [_revision("preview-result-v1.1", PREVIEW, "current")],
            },
            {
                "subject": "e7_runtime_verdict:bulk_rename:apply",
                "revisions": [_revision("apply-result-v1.2", APPLY, "current")],
            },
        ]
    )
    registry = {
        "schema": "marvin.evidence-supersession-registry/1.0",
        "status": "current",
        "generated_at": datetime.now(UTC).isoformat(),
        "preregistration": _artifact(POLICY),
        "preregistration_commit": PREREGISTRATION_COMMIT,
        "historical_artifacts_modified": False,
        "subject_granularity": True,
        "subjects": subjects,
        "summary": {
            "subjects": len(subjects),
            "surface_subjects": len(contract_ids),
            "partially_superseded_surface_subjects": len(changed),
            "surface_subjects_remaining_on_v1_4": len(contract_ids) - len(changed),
            "explicit_e7_verified_pairs": len(explicit_e7),
        },
        "rollback": policy["rollback"],
    }
    validate_registry(registry, root=ROOT)
    _write_atomic(REGISTRY, registry)
    return registry


if __name__ == "__main__":
    report = build_registry()
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
