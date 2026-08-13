from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evidence_portability import matches_frozen_sha256

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.2"
RESULT_SHA256 = "cc0861024baaf4902a8a422ec4322ed1f73eee29f549e8eb5bbe98cb8734fb53"


def canonical_hash(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    result_path = BASE / "e7-apply-replay-result.json"
    assert matches_frozen_sha256(result_path, RESULT_SHA256, root=ROOT)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    content_hash = result.pop("content_sha256")
    assert canonical_hash(result) == content_hash
    assert result["source_commit"] == "1d317a148b3c594d2129ffd06f084c6bec36c713"
    assert result["final_verdict"] == "R_CONFIRMED"
    assert result["cycles_required"] == result["cycles_completed"] == 5
    assert result["normalized_cycles_identical"] is True
    assert result["runner_reclassified_taxonomy"] is False
    assert result["business_tools_invoked"] == [{"tool": "bulk_rename", "action": "apply", "count": 5}]
    assert result["fixture_contains_user_data"] is False
    assert result["real_marvin_data_dir_used"] is False
    assert result["persistent_host_paths_used"] is False
    assert all(cycle["verdict"] == "R_CONFIRMED" for cycle in result["cycles"])
    assert all(cycle["business_tool_invocations"] == 1 for cycle in result["cycles"])
    assert all(cycle["central_manifest_verified"] is True for cycle in result["cycles"])
    assert all(cycle["exact_identity_restored"] is True for cycle in result["cycles"])
    assert all(cycle["preimage_sha256"] == cycle["restored_sha256"] for cycle in result["cycles"])
    assert all(not cycle["acl_added_rights"] and not cycle["residual_fields"] for cycle in result["cycles"])
    print("E7 Apply Replay Result v1.2 OK - R confirmed over five isolated cycles, taxonomy unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
