"""Verrouille le contexte borné et le batching familial Stage B."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
ERRATUM = ROOT / "benchmarks/tool-selection/v1.2/holdout-generator-erratum-v1.7.json"
def main() -> None:
    value = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_after_oracle_context_transport_failure_before_holdout_freeze"
    assert value["candidate_artifacts_are_not_frozen"]
    assert value["observation"]["business_tool_execution_count"] == 0
    assert value["observation"]["benchmark_model_call_count"] == 0
    change = value["authorized_change"]
    assert change["author_receives_family_contract_without_tool_catalog"]
    assert change["other_roles_receive_relevant_catalog_subset"]
    assert change["oracle_adjudicator_and_critic_calls_batched_by_family"]
    assert change["all_candidates_still_reviewed_by_both_oracles_adjudicator_and_critic"]
    assert change["same_models_prompts_seeds_temperature_top_p_and_semantic_rules"]
    assert change["no_client_num_ctx"]
    source = ROOT / value["source_generator"]["path"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == value["source_generator"]["sha256"]
    print("Stage B family batching erratum OK - bounded context, all candidates retained.")
if __name__ == "__main__": main()
