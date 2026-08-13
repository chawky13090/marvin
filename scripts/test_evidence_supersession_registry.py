"""Vérifie les chaînes de vérité, les canaris négatifs et l'inventaire E7 courant."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evidence_supersession import load_and_validate, validate_registry  # noqa: E402


REGISTRY_PATH = ROOT / "benchmarks" / "evidence-governance" / "v1" / "supersession-registry.json"
INVENTORY_PATH = ROOT / "benchmarks" / "tool-evidence" / "v1.2" / "inventory.json"
PREREGISTRATION_COMMIT = "6627e64a411bdeb68b1c7232a44e41b3e11c5d30"


def _expect_refused(value: dict, fragment: str) -> None:
    try:
        validate_registry(value, root=ROOT)
    except ValueError as exc:
        assert fragment.casefold() in str(exc).casefold(), str(exc)
    else:
        raise AssertionError(f"Le registre fautif aurait dû être refusé : {fragment}")


def main() -> int:
    registry, terminals = load_and_validate(REGISTRY_PATH, root=ROOT)
    assert registry["preregistration_commit"] == PREREGISTRATION_COMMIT
    assert registry["historical_artifacts_modified"] is False
    assert registry["summary"] == {
        "subjects": 25,
        "surface_subjects": 22,
        "partially_superseded_surface_subjects": 5,
        "surface_subjects_remaining_on_v1_4": 17,
        "explicit_e7_verified_pairs": 2,
    }
    assert terminals["tool_evidence_inventory:global"]["artifact"]["path"] == (
        "benchmarks/tool-evidence/v1.2/inventory.json"
    )
    surface_terminals = {
        subject: revision for subject, revision in terminals.items()
        if subject.startswith("e7_direct_surface_contract:")
    }
    assert len(surface_terminals) == 22
    assert sum(item["id"] == "surface-v1.5" for item in surface_terminals.values()) == 5
    assert sum(item["id"] == "surface-v1.4" for item in surface_terminals.values()) == 17

    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert inventory["schema_version"] == "1.2"
    assert inventory["governance"]["status"] == "current_terminal_evidence_only"
    summary = inventory["summary"]["evidence_assessment_by_level"]["E7"]
    assert summary == {"verified": 2, "absent": 0, "unassessed": 434}
    pairs = {(row["tool"], row["action"]): row for row in inventory["items"]}
    assert pairs[("bulk_rename", "preview")]["evidence"]["E7"] is True
    assert pairs[("bulk_rename", "apply")]["evidence"]["E7"] is True
    assert pairs[("bulk_rename", "rollback")]["evidence"]["E7"] is None
    assert pairs[("bulk_rename", "preview")]["explicit_evidence"]["E7"]["verdict"] == "N_CONFIRMED"
    assert pairs[("bulk_rename", "apply")]["explicit_evidence"]["E7"]["verdict"] == "R_CONFIRMED"
    for action in ("preview", "apply"):
        evidence = pairs[("bulk_rename", action)]["explicit_evidence"]["E7"]
        terminal = terminals[f"e7_runtime_verdict:bulk_rename:{action}"]["artifact"]
        assert evidence["artifact"] == terminal["path"]
        assert evidence["sha256"] == terminal["sha256"]

    historical_paths = {
        revision["artifact"]["path"]
        for subject in registry["subjects"]
        for revision in subject["revisions"]
        if revision["artifact"]["path"] not in {
            "benchmarks/tool-evidence/v1.2/inventory.json"
        }
    }
    for relative in historical_paths:
        blob = subprocess.run(
            ["git", "show", f"{PREREGISTRATION_COMMIT}:{relative}"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        assert hashlib.sha256(blob).hexdigest() == hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()

    cycle = copy.deepcopy(registry)
    revisions = cycle["subjects"][0]["revisions"]
    revisions[0]["successor"] = revisions[2]["id"]
    revisions[1]["successor"] = revisions[1]["id"]
    _expect_refused(cycle, "cycle")

    missing = copy.deepcopy(registry)
    missing["subjects"][0]["revisions"][0]["successor"] = "absent"
    _expect_refused(missing, "successeur absent")

    concurrent = copy.deepcopy(registry)
    revisions = concurrent["subjects"][0]["revisions"]
    revisions[0]["successor"] = revisions[2]["id"]
    _expect_refused(concurrent, "concurrents")

    bad_hash = copy.deepcopy(registry)
    bad_hash["subjects"][0]["revisions"][0]["artifact"]["sha256"] = "0" * 64
    _expect_refused(bad_hash, "empreinte divergente")
    print("Evidence Supersession Registry OK - 25 sujets, 2 E7 courants, canaris fermés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
