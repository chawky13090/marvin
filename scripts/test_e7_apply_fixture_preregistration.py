from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "e7-apply-preregistration.json"
MANIFEST = ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "e7-apply-preregistration-manifest.json"

import sys

sys.path.insert(0, str(ROOT / "scripts"))

from e7_apply_fixture import (  # noqa: E402
    ApplyFixtureError,
    assert_declared_rename_delta,
    build_apply_fixture,
    restore_by_inverse_rename,
    snapshot_apply_tree,
    validate_simple_rename_plan,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _refused(plan: dict[str, str], expected: str) -> None:
    try:
        validate_simple_rename_plan(plan)
    except ApplyFixtureError as exc:
        assert str(exc) == expected
    else:
        raise AssertionError(f"Le plan dangereux a ete accepte: {plan}")


def main() -> int:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert policy["schema"] == "marvin.e7-apply-preregistration/1.0"
    assert policy["status"] == "preregistered_execution_locked"
    assert policy["contract"] == "bulk_rename:apply"
    assert policy["required_e7_class"] == "R"
    assert policy["tool_execution_authorized"] is False
    assert policy["host_execution_forbidden"] is True
    assert policy["cycles"] == 5
    assert policy["maximum_business_tool_invocations_per_cycle"] == 1
    assert policy["maximum_total_business_tool_invocations"] == 5
    assert policy["all_other_pilot_contracts_authorized"] is False
    assert policy["fixture"]["chains_and_cycles_forbidden"] is True
    assert policy["fixture"]["casefold_collisions_forbidden"] is True
    assert policy["fixture"]["distinct_acl_canary_required"] is True
    assert policy["recovery"]["public_marvin_tools_used"] == []
    assert policy["recovery"]["bulk_rename_rollback_forbidden"] is True
    assert policy["intercycle_equivalence"]["absolute_paths_excluded"] is True
    assert policy["intercycle_equivalence"]["absolute_timestamps_excluded"] is True
    assert policy["publication"]["requires_all_five_cycles"] is True
    assert policy["publication"]["result_artifact_authorized"] is False
    assert policy["next_phase"]["runner_must_be_frozen_before_authorization"] is True

    for relative, expected in policy["governed_source_hashes"].items():
        assert _sha256(ROOT / relative) == expected, relative

    for relative, expected in manifest["files"].items():
        assert _sha256(ROOT / relative) == expected, relative
    assert manifest["tool_execution_authorized"] is False

    _refused({"A.txt": "B.txt", "B.txt": "C.txt"}, "fixture_rename_chain_or_cycle_forbidden")
    _refused({"A.txt": "B.txt", "B.txt": "A.txt"}, "fixture_rename_chain_or_cycle_forbidden")
    _refused({"A.txt": "new.txt", "a.TXT": "other.txt"}, "fixture_rename_casefold_collision")
    _refused({"../A.txt": "new.txt"}, "fixture_rename_path_not_simple_relative")

    normalized_cycles = []
    with tempfile.TemporaryDirectory(prefix="marvin-e7-apply-preregister-") as temporary:
        workspace = Path(temporary)
        for cycle_index in range(1, 6):
            fixture = build_apply_fixture(workspace, cycle_index)
            root = fixture["root"]
            preimage = fixture["preimage"]
            for source, target in validate_simple_rename_plan(fixture["plan"]):
                os.rename(root / source, root / target)
            mutated = snapshot_apply_tree(root)
            delta = assert_declared_rename_delta(preimage, mutated, fixture["plan"])
            recovery = restore_by_inverse_rename(root, fixture["plan"], preimage)
            assert snapshot_apply_tree(root) == preimage
            normalized_cycles.append({
                "verdict": "fixture_method_verified_without_business_tool",
                "relative_renames": delta["renames"],
                "restored_exact_identity": recovery["exact_identity"],
                "collateral_delta_count": 0,
                "business_tool_invocations": 0,
            })
    assert all(item == normalized_cycles[0] for item in normalized_cycles)

    print("E7 Apply Preregistration OK - politique gelee, fixture R exacte, outil metier verrouille.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
