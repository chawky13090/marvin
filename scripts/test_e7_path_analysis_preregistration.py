from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.4"


def main() -> int:
    policy = json.loads((BASE / "path-analysis-preregistration.json").read_text(encoding="utf-8"))
    rules = json.loads((BASE / "path-analysis-rules.json").read_text(encoding="utf-8"))
    canaries = ROOT / policy["prospective_canaries"]["source"]
    source = canaries.read_text(encoding="utf-8")
    assert policy["scope"]["contracts"] == 22
    assert policy["scope"]["tool_execution_authorized"] is False
    assert policy["scope"]["contract_mutation_authorized"] is False
    assert policy["unknown_transition_policy"]["silent_transition_forbidden"] is True
    assert policy["retrospective_validation"]["performed_only_after_v1_4_publication"] is True
    assert rules["invariants"]["no_special_case_by_tool_or_action"] is True
    assert rules["invariants"]["read_or_observe_never_counts_as_mutation"] is True
    for forbidden in ("note_delete", "bulk_rename", "vm_lab_install", "code_workspace"):
        assert forbidden not in json.dumps(rules).casefold()
        assert forbidden not in source.casefold()
    assert "dynamic_guard" in source and "early_return" in source and "nested_action" in source
    digest = hashlib.sha256(canaries.read_bytes()).hexdigest()
    assert len(digest) == 64
    print(f"E7 Path Analysis Preregistration OK - 22 contracts, prospective canaries {digest[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
