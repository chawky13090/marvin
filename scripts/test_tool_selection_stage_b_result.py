"""Vérifie la preuve brute B1 sans réinterpréter ses seuils."""
from __future__ import annotations
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.2"

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> None:
    result_path = BASE / "stage-b-b1-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    policy = json.loads((BASE / "stage-b-preregistration.json").read_text(encoding="utf-8"))
    freeze = json.loads((BASE / "stage-b-runner-freeze.json").read_text(encoding="utf-8"))
    authorization = json.loads((BASE / "stage-b-b1-authorization.json").read_text(encoding="utf-8"))
    corpus = json.loads((BASE / "holdout-corpus.json").read_text(encoding="utf-8"))["items"]

    assert result["status"] == "complete"
    assert result["policy_sha256"] == digest(BASE / "stage-b-preregistration.json")
    assert result["holdout_freeze_sha256"] == digest(BASE / "holdout-freeze-manifest.json")
    assert result["runner_freeze_sha256"] == digest(BASE / "stage-b-runner-freeze.json")
    assert result["authorization_sha256"] == digest(BASE / "stage-b-b1-authorization.json")
    assert result["runner_sha256"] == freeze["frozen_hashes"]["scripts/run_tool_selection_stage_b.py"]
    assert result["candidate_matrix_sha256"] == freeze["preflight"]["candidate_matrix_sha256"]
    assert result["system_prompt_sha256"] == freeze["preflight"]["system_prompt_sha256"]
    assert result["benchmark_model"] == policy["independent_roles"]["benchmark"]
    assert result["benchmark_model_observed"] == ["mistral-large-3:675b"]
    assert result["client_num_ctx"] is None
    assert result["business_tool_execution_count"] == 0
    assert result["host_side_effect_count"] == 0
    assert authorization["authorization_consumed_when_result_exists"] is True

    observations = result["observations"]
    assert len(observations) == authorization["maximum_model_calls"] == 810
    expected_ids = {row["id"] for row in corpus}
    assert {row["id"] for row in observations} == expected_ids
    cells = Counter((row["id"], row["mode"], row["configuration"]) for row in observations)
    assert len(cells) == 270 and set(cells.values()) == {3}
    assert all(row["public_tool_name_valid"] for row in observations)
    assert all(row["candidate_membership_valid"] for row in observations if row["name"] is not None)
    assert all(1 <= row["attempts"] <= 3 for row in observations)
    assert all("content" not in row and "raw_response" not in row for row in observations)
    assert all(len(row["content_sha256"]) == 64 for row in observations)
    assert set(result["aggregates"]) == set(policy["experiment"]["modes"])
    assert all(set(rows) == set(policy["experiment"]["configurations"]) for rows in result["aggregates"].values())
    print(f"Stage B B1 result OK - {len(observations)} choices, zero execution, sha256={digest(result_path)}")

if __name__ == "__main__":
    main()
