"""Contrat de gel E7 R/C/I/N/P et de non-exécution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from e7_taxonomy_freeze import BASE, ROOT, validate


def main() -> int:
    summary = validate()
    assert summary["classified_pairs"] == 36
    assert summary["class_counts"] == {"C": 12, "I": 2, "N": 2, "P": 14, "R": 6}
    assert summary["execution_authorized"] is False
    manifest = json.loads((BASE / "e7-freeze-manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "frozen_before_fixture_design"
    assert manifest["tool_execution_authorized"] is False
    for relative, expected in manifest["source_hashes"].items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert actual == expected, relative
    policy = json.loads((BASE / "e7-taxonomy-policy.json").read_text(encoding="utf-8"))
    assert policy["invariants"]["missing_rollback_implementation_never_justifies_I"] is True
    assert policy["invariants"]["P_never_grants_E7_at_tool_action_level"] is True
    print("E7 Taxonomy Freeze OK - 36 couples, R/C/I/N/P, empreintes et exécution verrouillée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
