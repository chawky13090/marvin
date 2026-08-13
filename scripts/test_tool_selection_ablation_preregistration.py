"""Verrouille le protocole d'ablation avant son runner et toute façade produit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks" / "tool-selection" / "v1.0" / "ablation-preregistration.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _blob(commit: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, relative_path
    return result.stdout


def main() -> int:
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_before_ablation_runner"
    assert value["product_change_authorized"] is False
    assert value["chat_llm_call_authorized"] is False
    assert value["business_tool_execution_authorized"] is False
    assert value["side_effect_authorized"] is False
    for relative_path, expected in value["product_sources_sha256"].items():
        assert hashlib.sha256(_blob(value["source_commit"], relative_path)).hexdigest() == expected
    for relative_path, expected in value["public_inputs_sha256"].items():
        assert _sha256(ROOT / relative_path) == expected
    private_available = True
    for item in value["private_inputs"].values():
        if not isinstance(item, dict) or "path" not in item:
            continue
        path = ROOT / item["path"]
        if path.exists():
            assert _sha256(path) == item["sha256"]
        else:
            private_available = False
    assert value["private_inputs"]["absence_never_fails_portable_gate"] is True
    assert value["configurations"] == ["K", "L", "S", "K+L", "K+S", "L+S", "K+L+S"]
    assert value["modes"] == {"eco": 18, "balanced": 40, "performance": 80, "max": 250}
    assert value["semantic_protocol"]["repetitions"] == 1
    assert value["private_compatibility_panel"]["correctness_claim_forbidden"] is True
    assert value["decision"]["security_guards_never_ablated"] is True
    assert value["decision"]["stage_a_never_removes_product_layer"] is True
    assert value["gate_scope"]["portable_public_canary_only"] is True
    assert value["rollback"]["persistent_data_mutation"] is False
    print(
        "Tool Selection Ablation Preregistration OK - 7 configurations, 4 modes, "
        f"private_available={str(private_available).lower()}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
