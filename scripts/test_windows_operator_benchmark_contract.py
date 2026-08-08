"""Garde anti-dérive du contrat Forge Windows Operator v1."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_V1 = ROOT / "benchmarks" / "windows-operator" / "v1"
CONTRACT = ROOT / "benchmarks" / "windows-operator" / "v1.1"


def read_json(name: str) -> dict:
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


def main() -> int:
    acceptance = read_json("acceptance-policy.json")
    plan = read_json("benchmark-plan.json")
    schema = read_json("scenario-contract.schema.json")

    legacy = json.loads((CONTRACT_V1 / "acceptance-policy.json").read_text(encoding="utf-8"))
    assert legacy["schema"] == "marvin.windows-operator-acceptance/1.0"
    assert legacy["context_precondition"]["cloud_evidence"] == "ollama_cloud_full_context"

    assert acceptance["status"] == "locked_before_baseline"
    assert acceptance["supersedes"] == "../v1/acceptance-policy.json"
    context = acceptance["context_precondition"]
    assert context["minimum_tokens"] == 32_768
    assert context["recommended_tokens"] == 65_536
    assert context["cloud_evidence"] == "cloud_provider_declared_max"
    assert context["cloud_runtime_allocation"] == "unavailable"
    assert context["cloud_long_context_behavioral_test_required"] is True

    outcomes = acceptance["outcomes"]
    assert set(outcomes) == {"generalized", "restricted", "rollback"}
    generalized_metrics = {
        item.get("metric")
        for item in outcomes["generalized"]["all"]
        if isinstance(item, dict)
    }
    assert "intelligence_regression_count" in generalized_metrics
    intelligence = acceptance["intelligence_preservation"]
    assert intelligence["cloud_client_context_override_count"] == 0
    assert intelligence["cloud_behavioral_retention_must_not_regress"] is True
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
    assert plan["model_policy"]["runtime_lock_required"] is True
    assert plan["model_policy"]["runtime_lock_environment"] == "MARVIN_FORGE_RUNTIME_LOCK"
    assert plan["model_policy"]["runtime_lock_drift_policy"] == "fail_closed_and_discard_run"
    assert plan["model_policy"]["cloud_context_policy"] == "provider_declared_max_without_client_override"
    assert plan["model_policy"]["cloud_behavioral_retention_test_required"] is True
    assert plan["model_policy"]["quality_and_capability_regression_suite_required"] is True

    required = set(schema["required"])
    assert {"fixture_id", "oracle_id", "risk_class", "reversible"} <= required
    assert schema["additionalProperties"] is False

    runtime_source = (ROOT / "backend" / "ollama_context_runtime.py").read_text(encoding="utf-8")
    agent_source = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
    admission_source = (ROOT / "backend" / "ollama_context_admission.py").read_text(encoding="utf-8")
    cloud_probe = (ROOT / "scripts" / "probe-ollama-cloud-context.py").read_text(encoding="utf-8")
    assert "cloud_provider_declared_max" in runtime_source
    assert '"options": {"num_ctx"' not in agent_source
    assert "'options': {'num_ctx'" not in agent_source
    assert "load_active_lock" in admission_source
    assert "cloud_client_override_absent" in admission_source
    assert '"num_ctx"' not in cloud_probe
    assert '"client_context_override": None' in cloud_probe

    print("Windows operator benchmark contract OK - seuils, répétitions et isolation figés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
