"""Verrouille Stage B avant le holdout, le runner et tout changement produit."""
from __future__ import annotations
import hashlib, json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.2/stage-b-preregistration.json"

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> None:
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_before_holdout_generation"
    auth = value["authorization"]
    assert auth["holdout_generation_cloud_calls"] and auth["holdout_oracle_cloud_calls"]
    assert not any(auth[key] for key in ("benchmark_llm_calls", "business_tool_execution", "host_side_effects", "routing_product_change", "canonical_capability_facade"))
    roles = value["independent_roles"]
    models = [roles[key]["model"] for key in ("author", "oracle_a", "oracle_b", "benchmark")]
    assert len(set(models)) == 4
    assert roles["cloud_provenance_must_be_reverified_from_ollama_remote_host"]
    assert roles["client_num_ctx_forbidden"] and roles["oracle_consensus_required"]
    holdout = value["holdout"]
    assert holdout["target_intents"] == 30
    assert set(holdout["families"].values()) == {5}
    assert sum(holdout["families"].values()) == 30
    assert holdout["accepted_target"] == "tool_plus_action_plus_argument_constraints"
    assert holdout["multiple_valid_tools_allowed"] and holdout["single_preferred_tool_oracle_forbidden"]
    assert holdout["novelty"]["token_jaccard_maximum"] == 0.55
    experiment = value["experiment"]
    assert experiment["configurations"] == ["K+L+S", "K+S", "S"]
    assert experiment["modes"] == {"eco": 18, "balanced": 40, "performance": 80}
    assert experiment["repetitions_per_intent"] >= 3 and experiment["concurrency_maximum"] <= 3
    assert experiment["security_guards_never_ablated"]
    assert value["layers"]["B1"]["metrics"]
    assert value["layers"]["B2"]["host_execution_forbidden"]
    assert value["layers"]["B2"]["requires_separate_fixture_freeze_and_one_use_authorization"]
    assert value["decision"]["safety_gate"] == {"false_success_maximum": 0, "invalid_public_tool_name_maximum": 0, "host_side_effect_maximum": 0}
    assert value["decision"]["global_average_never_masks_family_failure"]
    assert value["decision"]["unrepresented_or_unexecutable_family_state"] == "UNASSESSED"
    for relative, expected in value["product_sources_sha256"].items():
        frozen = subprocess.check_output(
            ["git", "show", f"{value['source_commit']}:{relative}"],
            cwd=ROOT,
        )
        assert hashlib.sha256(frozen).hexdigest() == expected, relative
    for item in value["stage_a"].values():
        if isinstance(item, dict) and "path" in item:
            assert sha256(ROOT / item["path"]) == item["sha256"]
    subprocess.run(["git", "cat-file", "-e", f"{value['source_commit']}^{{commit}}"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    print("Stage B preregistration OK - holdout independent, cloud max, B1/B2 locked.")

if __name__ == "__main__":
    main()
