from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.1"
OUTPUT = BASE / "e7-preview-execution-policy.json"
GOVERNED = (
    "benchmarks/tool-evidence/v1.1/direct-fixture-pilot.json",
    "scripts/e7_fixture_harness/surface_runtime.py",
    "scripts/run_e7_preview_campaign.py",
    "backend/tool_domains/filesystem.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    pilot = json.loads((BASE / "direct-fixture-pilot.json").read_text(encoding="utf-8"))
    preview = [
        item for item in pilot["contracts"]
        if item["tool"] == "bulk_rename" and item["action"] == "preview"
    ]
    if len(preview) != 1 or preview[0]["class"] != "N":
        raise RuntimeError("Le contrat bulk_rename:preview gele est absent ou ambigu.")
    policy = {
        "schema": "marvin.e7-preview-execution-policy/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "preregistered_not_executed",
        "authorized_contracts": ["bulk_rename:preview"],
        "all_other_pilot_contracts_authorized": False,
        "maximum_business_tool_invocations": 1,
        "host_persistent_path_forbidden": True,
        "isolation": "isolated_temp_volume",
        "required_e7_class": "N",
        "required_outcome": {
            "confirmation_preview_returned": True,
            "observable_mutation_count": 0,
            "before_after_snapshot_identical": True,
        },
        "result_path": "benchmarks/tool-evidence/v1.1/e7-preview-execution-result.json",
        "governed_source_hashes": {
            relative: _sha256(ROOT / relative) for relative in GOVERNED
        },
        "rollback": "delete_result_artifact_and_revert_preregistration_commit",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(f"E7 preview policy frozen: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
