"""Garde anti-dérive du contrat Forge Windows Operator v1."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "benchmarks" / "windows-operator" / "v1"


def read_json(name: str) -> dict:
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


def main() -> int:
    acceptance = read_json("acceptance-policy.json")
    plan = read_json("benchmark-plan.json")
    schema = read_json("scenario-contract.schema.json")

    assert acceptance["status"] == "locked_before_baseline"
    context = acceptance["context_precondition"]
    assert context["minimum_tokens"] == 32_768
    assert context["recommended_tokens"] == 65_536
    assert context["cloud_evidence"] == "ollama_cloud_full_context"

    outcomes = acceptance["outcomes"]
    assert set(outcomes) == {"generalized", "restricted", "rollback"}
    generalized_metrics = {
        item.get("metric")
        for item in outcomes["generalized"]["all"]
        if isinstance(item, dict)
    }
    assert "intelligence_regression_count" in generalized_metrics
    intelligence = acceptance["intelligence_preservation"]
    assert intelligence["cloud_effective_to_max_context_ratio"] == 1.0
    assert intelligence["council_distinct_model_families_minimum"] == 5
    assert intelligence["tool_catalog_may_shrink"] is False
    assert acceptance["redundant_confirmation"]["target_count"] == 0
    assert acceptance["statistical_gates"]["engineering_live_runs"] == 75
    assert acceptance["statistical_gates"]["general_release_live_runs"] == 300

    assert plan["intent_corpus"] == {
        "total": 120,
        "development": 80,
        "holdout": 40,
        "runs_per_intent": 3,
    }
    assert plan["live_scenarios"]["total"] == 15
    assert plan["live_scenarios"]["development"] == 10
    assert plan["live_scenarios"]["holdout"] == 5
    assert plan["live_scenarios"]["runs_per_scenario"] == 5
    assert [layer["id"] for layer in plan["layers"]] == [
        "routing",
        "operator",
        "end_to_end",
    ]

    isolation = plan["state_isolation"]
    assert isolation["automated_setup_required_before_every_run"] is True
    assert isolation["independent_oracle_required_after_every_run"] is True
    assert isolation["teardown_required_in_finally"] is True
    assert isolation["cleanup_on_interruption_required"] is True
    assert isolation["manual_setup_allowed"] is False
    assert isolation["manual_oracle_allowed"] is False

    catalog = plan["catalog_policy"]
    assert catalog["candidate"] == "windows_task_visible_computer_control_internal"
    assert catalog["both_visible_in_production"] is False
    assert plan["model_policy"]["dynamic_routing_allowed"] is False
    assert plan["model_policy"]["ollama_context_evidence_required"] is True
    assert plan["model_policy"]["cloud_context_policy"] == "provider_maximum"
    assert plan["model_policy"]["quality_and_capability_regression_suite_required"] is True

    required = set(schema["required"])
    assert {"fixture_id", "oracle_id", "risk_class", "reversible"} <= required
    assert schema["additionalProperties"] is False

    runtime_source = (ROOT / "backend" / "ollama_context_runtime.py").read_text(encoding="utf-8")
    agent_source = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
    assert "ollama_cloud_full_context" in runtime_source
    assert '"options": {"num_ctx"' not in agent_source
    assert "'options': {'num_ctx'" not in agent_source

    print("Windows operator benchmark contract OK - seuils, répétitions et isolation figés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
