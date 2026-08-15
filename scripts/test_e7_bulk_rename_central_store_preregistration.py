from __future__ import annotations
import json
import hashlib
import subprocess
from pathlib import Path

from evidence_portability import matches_frozen_sha256

ROOT = Path(__file__).resolve().parents[1]
V11 = ROOT / "benchmarks" / "tool-evidence" / "v1.1"
POLICY = ROOT / "benchmarks" / "tool-evidence" / "v1.2" / "bulk-rename-central-store-preregistration.json"
ERRATUM = ROOT / "benchmarks" / "tool-evidence" / "v1.2" / "central-store-governed-source-erratum.json"

def _blob_sha256(commit: str, relative: str) -> str:
    blob = subprocess.run(
        ["git", "show", f"{commit}:{relative}"], cwd=ROOT,
        check=True, capture_output=True,
    ).stdout
    return hashlib.sha256(blob).hexdigest()

def main() -> int:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["status"] == "preregistered_execution_locked"
    assert policy["tool_execution_authorized"] is policy["campaign_replay_authorized"] is policy["taxonomy_mutation_authorized"] is False
    assert matches_frozen_sha256(ROOT / policy["historical_result_preserved"]["path"], policy["historical_result_preserved"]["sha256"], root=ROOT)
    assert matches_frozen_sha256(ROOT / policy["historical_assessment_preserved"]["path"], policy["historical_assessment_preserved"]["sha256"], root=ROOT)
    preview = policy["historical_preview_preserved"]
    assert matches_frozen_sha256(ROOT / preview["policy_path"], preview["policy_sha256"], root=ROOT)
    assert matches_frozen_sha256(ROOT / preview["result_path"], preview["result_sha256"], root=ROOT)
    old_prereg = json.loads((V11 / "e7-apply-preregistration-manifest.json").read_text(encoding="utf-8"))
    old_runner = json.loads((V11 / "e7-apply-execution-freeze-manifest.json").read_text(encoding="utf-8"))
    assert old_prereg["files"]["backend/tool_domains/filesystem.py"] == policy["previous_governed_source_sha256"]
    assert old_runner["frozen_hashes"]["backend/tool_domains/filesystem.py"] == policy["previous_governed_source_sha256"]
    erratum = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert erratum["historical_artifact_edited"] is False
    for relative, expected in policy["current_governed_sources"].items():
        assert _blob_sha256(erratum["historical_source_commit"], relative) == expected, relative
    assert all(policy["product_invariants"].values())
    print("E7 bulk rename v1.2 OK - v1.1 immutable, product fix frozen, replay locked.")
    return 0

if __name__ == "__main__": raise SystemExit(main())
