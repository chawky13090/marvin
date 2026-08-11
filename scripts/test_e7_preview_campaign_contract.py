from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.1"
sys.path.insert(0, str(ROOT / "scripts"))

from run_e7_preview_campaign import CampaignRefused, validate_policy  # noqa: E402


def main() -> int:
    policy_path = BASE / "e7-preview-execution-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    governed = validate_policy(policy)
    assert "scripts/run_e7_preview_campaign.py" in governed

    changed = json.loads(json.dumps(policy))
    changed["authorized_contracts"] = ["bulk_rename:apply"]
    try:
        validate_policy(changed)
    except CampaignRefused:
        pass
    else:
        raise AssertionError("Une autorisation E7 elargie a ete acceptee.")

    result_path = BASE / "e7-preview-execution-result.json"
    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["status"] == "verified"
        assert result["contract"] == "bulk_rename:preview"
        assert result["business_tools_invoked"] == [
            {"tool": "bulk_rename", "action": "preview", "count": 1}
        ]
        assert result["all_other_pilot_contracts_invoked"] is False
        assert result["observable_mutation_count"] == 0
        assert result["snapshots_identical"] is True
        assert result["before_snapshot_sha256"] == result["after_snapshot_sha256"]
        assert result["policy_sha256"] == hashlib.sha256(policy_path.read_bytes()).hexdigest()

    print("E7 Preview Campaign Contract OK - autorisation unique, sources gelees et preuve bornee.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
