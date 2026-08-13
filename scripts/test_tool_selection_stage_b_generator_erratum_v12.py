"""Verrouille la séparation auteur/oracles du générateur Stage B v1.2."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRATUM = ROOT / "benchmarks/tool-selection/v1.2/holdout-generator-erratum-v1.2.json"

def main() -> None:
    value = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_after_second_aborted_generation_before_any_artifact"
    assert value["observation"]["published_artifact_count"] == 0
    assert value["observation"]["business_tool_execution_count"] == 0
    change = value["authorized_change"]
    assert change["author_argument_facts_are_ignored"]
    assert change["author_role_reduced_to_family_and_prompt_only"]
    assert change["both_independent_oracles_derive_argument_constraints_from_prompt"]
    assert change["prompt_family_novelty_privacy_and_decision_rules_unchanged"]
    source = ROOT / value["source_generator"]["path"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == value["source_generator"]["sha256"]
    print("Stage B generator erratum v1.2 OK - author cannot label arguments.")

if __name__ == "__main__": main()
