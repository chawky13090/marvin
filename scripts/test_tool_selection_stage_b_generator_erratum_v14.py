"""Verrouille les retries Cloud bornés du générateur Stage B."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
ERRATUM = ROOT / "benchmarks/tool-selection/v1.2/holdout-generator-erratum-v1.4.json"
def main() -> None:
    value = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_after_third_aborted_generation_before_any_artifact"
    assert value["observation"]["published_artifact_count"] == 0
    change = value["authorized_change"]
    assert change["maximum_attempts_per_cloud_role"] == 3
    assert change["same_model_prompt_seed_temperature_and_top_p_required"]
    assert change["retry_only_on_transport_http_or_json_contract_failure"]
    assert change["semantic_validation_failure_is_not_retryable"]
    assert change["attempt_count_must_be_published"]
    source = ROOT / value["source_generator"]["path"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == value["source_generator"]["sha256"]
    print("Stage B Cloud retry erratum OK - same request, max three attempts.")
if __name__ == "__main__": main()
