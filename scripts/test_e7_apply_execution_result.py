from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from evidence_portability import matches_frozen_sha256


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.1"
RESULT = BASE / "e7-apply-execution-result.json"
ASSESSMENT = BASE / "e7-apply-execution-assessment.json"
MANIFEST_PATTERN = re.compile(r"^\.marvin-rollback/bulk-rename-[0-9a-f]{32}\.json$")


def canonical_hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assessment = json.loads(ASSESSMENT.read_text(encoding="utf-8"))
    assert matches_frozen_sha256(RESULT, assessment["source_result_sha256"], root=ROOT)
    recorded = result.pop("content_sha256")
    assert canonical_hash(result) == recorded
    assert result["final_verdict"] == "FAILED_LOCKED"
    assert result["runner_reclassified_taxonomy"] is False
    assert result["cycles_required"] == result["cycles_completed"] == 5
    assert result["business_tools_invoked"] == [
        {"tool": "bulk_rename", "action": "apply", "count": 5}
    ]
    assert result["all_other_business_tools_invoked"] is False
    for cycle in result["cycles"]:
        assert cycle["verdict"] == "FAILED_LOCKED"
        assert cycle["tool_success"] is True
        assert cycle["declared_delta_valid"] is False
        assert cycle["declared_delta_error"] == "fixture_rename_collateral_delta"
        assert cycle["exact_identity_restored"] is True
        assert cycle["acl_added_rights"] == {}
        assert cycle["independent_recovery_error"] is None
        collateral = cycle["collateral_paths"]
        assert collateral[0] == ".marvin-rollback"
        assert MANIFEST_PATTERN.fullmatch(collateral[1])
    assert assessment["taxonomy"]["changed_by_runner"] is False
    assert assessment["taxonomy"]["execution_lock_remains"] is True
    assert assessment["instrumentation_limit"]["effect_on_final_verdict"] == "none"
    print("E7 Apply Result OK - 5/5 tool successes, exact recovery, collateral rollback metadata, FAILED_LOCKED preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
