"""Verrouille la seule correction autorisée après le run auteur avorté."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRATUM = ROOT / "benchmarks/tool-selection/v1.2/holdout-generator-erratum-v1.1.json"

def main() -> None:
    value = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_after_aborted_generation_before_any_artifact"
    assert value["observation"]["published_artifact_count"] == 0
    assert value["observation"]["business_tool_execution_count"] == 0
    change = value["authorized_change"]
    assert change["model_authored_identifiers_are_ignored"]
    assert change["generator_assigns_deterministic_identifiers_from_family_and_ordinal"]
    assert change["prompt_family_and_argument_facts_validation_unchanged"]
    assert change["novelty_oracle_privacy_and_decision_rules_unchanged"]
    source = ROOT / value["source_generator"]["path"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == value["source_generator"]["sha256"]
    print("Stage B generator erratum OK - identifiers only, no semantic change.")

if __name__ == "__main__":
    main()
