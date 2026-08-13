"""Vérifie l'immuabilité, la confidentialité et la dérivation de l'ablation v1.1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ASSESSMENT = ROOT / "benchmarks/tool-selection/v1.1/ablation-assessment.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    assessment = load(ASSESSMENT)
    result_path = ROOT / assessment["source_result"]["path"]
    cache_path = ROOT / assessment["source_public_cache"]["path"]
    runner_path = ROOT / assessment["source_runner"]["path"]
    result = load(result_path)
    cache = load(cache_path)
    assert sha256(result_path) == assessment["source_result"]["sha256"]
    assert sha256(cache_path) == assessment["source_public_cache"]["sha256"]
    assert sha256(runner_path) == assessment["source_runner"]["sha256"]
    assert result["runner_sha256"] == sha256(runner_path)
    assert result["public_cache_sha256"] == sha256(cache_path)
    assert result["status"] == "complete_private_and_public"
    assert result["chat_llm_calls"] == 0
    assert result["business_tool_executions"] == 0
    signals = result["phase_durations_ms"]["signals"]
    assert signals["embedding"]["single_batch_exact_equality"] is True
    assert signals["route_control_exact_equality"] is True
    expected_public_ids = {
        str(item["id"])
        for item in load(
            ROOT / "benchmarks/windows-operator/v1.1/intent-corpus.json"
        )["items"]
    } | {
        str(item["id"])
        for item in load(
            ROOT / "benchmarks/tool-recovery/v1.2/development-corpus.json"
        )["items"]
    }
    assert set(cache["records"]) == expected_public_ids
    serialized_result = result_path.read_text(encoding="utf-8")
    serialized_cache = cache_path.read_text(encoding="utf-8")
    for forbidden in ("message_id", "conversation_id", '"text"', '"prompt"', "real-0001-"):
        assert forbidden not in serialized_result
        assert forbidden not in serialized_cache
    private_allowed = {
        "historical_pairs",
        "retained_pairs",
        "retention",
        "successful_historical_pairs",
        "retained_successful_pairs",
        "successful_retention",
    }
    for configurations in result["private_compatibility"].values():
        for value in configurations.values():
            assert set(value) == private_allowed
    assert assessment["layer_decision"] == {
        "K": result["layer_decisions"]["K"]["stage_a_state"],
        "L": result["layer_decisions"]["L"]["stage_a_state"],
        "S": result["layer_decisions"]["S"]["stage_a_state"],
        "product_layer_removal_authorized": False,
        "canonical_capability_facade_authorized": False,
    }
    full_recall = {
        mode: result["public_correctness"][mode]["K+L+S"]["recall"]
        for mode in ("eco", "balanced", "performance", "max")
    }
    assert full_recall == assessment["diagnostic_findings"]["full_recall"]
    full_retention = {
        mode: result["private_compatibility"][mode]["K+L+S"][
            "successful_retention"
        ]
        for mode in ("eco", "balanced", "performance", "max")
    }
    assert full_retention == assessment["diagnostic_findings"][
        "full_successful_historical_retention"
    ]
    assert assessment["stage_b"]["configurations"] == ["K+L+S", "K+S", "S"]
    assert assessment["stage_b"]["requires_new_independent_holdout"] is True
    assert assessment["stage_b"]["product_change_before_stage_b_forbidden"] is True
    print(
        "Tool Selection Ablation Result OK - "
        "raw immuable, privé agrégé, K/L/S requis et Stage B borné."
    )


if __name__ == "__main__":
    main()
