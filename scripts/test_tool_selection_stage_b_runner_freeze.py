"""Vérifie que l'appareil B1 gelé ne peut dériver avant exécution."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks/tool-selection/v1.2/stage-b-runner-freeze.json"

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> None:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_before_benchmark_model_invocation"
    for relative, expected in value["frozen_hashes"].items():
        path = ROOT / relative
        assert path.is_file() and digest(path) == expected, relative
    preflight = value["preflight"]
    assert preflight["record_count"] == 30
    assert preflight["candidate_matrix_cells"] == 270
    assert len(preflight["candidate_matrix_sha256"]) == 64
    assert len(preflight["system_prompt_sha256"]) == 64
    contract = value["execution_contract"]
    assert contract["expected_model_calls"] == 30 * 3 * 3 * 3
    assert contract["concurrency_maximum"] == 3
    assert contract["business_tool_execution_forbidden"] is True
    assert contract["host_side_effect_forbidden"] is True
    assert contract["partial_result_publication_forbidden"] is True
    assert value["authorization"]["benchmark_model_execution_authorized"] is False
    print("Stage B runner freeze OK - 810 choices, no execution, single-use authorization pending.")

if __name__ == "__main__":
    main()
