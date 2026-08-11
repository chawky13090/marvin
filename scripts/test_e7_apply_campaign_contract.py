from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.1"
sys.path.insert(0, str(ROOT / "scripts"))

from run_e7_apply_campaign import CampaignRefused, _acl_added_rights, _validate_frozen_inputs


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    policy, authorization, governed = _validate_frozen_inputs()
    manifest = json.loads((BASE / "e7-apply-execution-freeze-manifest.json").read_text(encoding="utf-8"))
    assert policy["verdicts"] == ["R_CONFIRMED", "R_INVALID_C_CANDIDATE", "FAILED_LOCKED"]
    assert policy["runner_may_reclassify_taxonomy"] is False
    assert policy["c_candidate_predicate"]["allowed_residual_fields"] == ["file_identity", "created_ns"]
    assert policy["c_candidate_predicate"]["any_added_acl_right_fails_locked"] is True
    assert policy["verdict_actions"]["R_INVALID_C_CANDIDATE"]["taxonomy_change"] == "forbidden_in_this_run"
    assert authorization["authorized_cycles"] == 5
    assert authorization["maximum_business_tool_invocations_per_cycle"] == 1
    assert authorization["result_artifact_authorized"] is True
    assert authorization["taxonomy_mutation_authorized"] is False
    assert len(governed) >= 5
    for relative, expected in manifest["frozen_hashes"].items():
        assert sha256(ROOT / relative) == expected, relative

    assert _acl_added_rights("O:S-1D:(A;;FR;;;S-1-1-0)", "O:S-1D:(A;;FR;;;S-1-1-0)") == []
    assert _acl_added_rights("O:S-1D:(A;;FR;;;S-1-1-0)", "O:S-1D:(A;;FR;;;S-1-1-0)(A;;FW;;;S-1-5-18)")

    changed = dict(authorization)
    changed["authorized_cycles"] = 6
    auth_path = BASE / "e7-apply-execution-authorization.json"
    original = auth_path.read_bytes()
    try:
        auth_path.write_bytes(json.dumps(changed).encode("utf-8"))
        try:
            _validate_frozen_inputs()
        except CampaignRefused:
            pass
        else:
            raise AssertionError("modified authorization accepted")
    finally:
        auth_path.write_bytes(original)

    print("E7 Apply Campaign Contract OK - runner frozen, three mechanical verdicts, five isolated cycles only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
