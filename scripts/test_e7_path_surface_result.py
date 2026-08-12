from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.4"
RESULT = BASE / "direct-path-surface-analysis.json"
TRANSITIONS = BASE / "v1.3-v1.4-transition-report.json"
RETROSPECTIVE = BASE / "retrospective-known-case-check.json"
EXPECTED_RESULT_SHA256 = "840ad9ae9333e3df76993dfeaf3c8301b4c520a15e48bcf8bdb221712fb3a8ed"
EXPECTED_TRANSITIONS_SHA256 = "77e94ce535ba0ca7f0c914e1e35d614c1a820597d5c7ebd4f18beff3025333ce"
EXPECTED_RETROSPECTIVE_SHA256 = "b4037ddbdd2c69d9d650e63d1233bd3b2b7d5f1085b28bb8d5159123708ee5eb"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    assert sha(RESULT) == EXPECTED_RESULT_SHA256
    assert sha(TRANSITIONS) == EXPECTED_TRANSITIONS_SHA256
    assert sha(RETROSPECTIVE) == EXPECTED_RETROSPECTIVE_SHA256
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    transitions = json.loads(TRANSITIONS.read_text(encoding="utf-8"))
    retrospective = json.loads(RETROSPECTIVE.read_text(encoding="utf-8"))
    assert result["contracts"] == 22
    assert result["tool_execution_performed"] is False
    assert result["contract_mutation_performed"] is False
    assert transitions["contracts"] == 22 and transitions["silent_transitions"] == 0
    assert transitions["v1_3_unknown_contracts_accounted_for"] == 13
    assert transitions["v1_4_sha256"] == sha(RESULT)
    assert retrospective["v1_4_sha256"] == sha(RESULT)
    assert retrospective["checks"]["known_multistore_delete"]["state"] == "CONFIRMED_UNDER_DECLARED"
    assert retrospective["checks"]["known_preview_with_early_return"]["compatible_mutations"]["total"] == 0
    status_items = retrospective["checks"]["known_status_with_reconciliation"]["effects"]["items"]
    assert any(item["target"] == "os.replace" and item["operation"] == "UPDATE" for item in status_items)
    analyzer = (ROOT / "scripts" / "e7_path_surface_analyzer.py").read_text(encoding="utf-8")
    for forbidden in ("note_delete", "bulk_rename", "vm_lab_install", "code_workspace"):
        assert forbidden not in analyzer.casefold()
    for item in result["results"]:
        for key in ("compatible_effects", "guarded_effects", "excluded_paths", "unresolved_paths"):
            bundle = item[key]
            assert set(bundle) == {"total", "sha256", "truncated", "items"}
            assert len(bundle["sha256"]) == 64
    print(f"E7 Path Surface Result OK - {result['counts']}, 13 prior UNKNOWN accounted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
