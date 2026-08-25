"""Validate the frozen software compensation boundary before implementation."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.7/software-remediation-preregistration.json"
ERRATUM = ROOT / "benchmarks/tool-selection/v1.7/software-remediation-source-erratum-v1.json"


def _sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def _blob_sha(commit: str, relative: str) -> str:
    blob = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(blob).hexdigest()


def main() -> None:
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_before_remediation_implementation"
    catalog = value["catalog_contract"]
    assert catalog["public_tool_count"] == 364
    assert catalog["public_tools_must_be_preserved"] is True
    assert catalog["candidate_budget_must_not_increase"] is True
    assert catalog["initial_install_candidates"] == ["winget_install"]
    assert catalog["initial_upgrade_candidates"] == ["winget_upgrade"]
    assert catalog["initial_install_or_upgrade_must_not_offer"] == ["winget_uninstall"]

    escalation = value["compensatory_escalation"]
    assert escalation["default"] == "denied"
    assert escalation["required_receipt_fields"] == {
        "status": "blocked",
        "blocker_type": "incompatible_existing_package",
        "remediation_requires_uninstall": True,
        "requested_package_id": "non_empty_exact_winget_id",
        "installed_package_id": "non_empty_exact_winget_id",
        "evidence_source": "winget_runtime_receipt",
    }
    assert escalation["all_fields_must_be_derived_from_runtime_observation"] is True
    assert escalation["llm_cannot_supply_or_override_receipt_fields"] is True
    assert escalation["uninstall_requires_new_owner_confirmation"] is True
    assert escalation["changed_digest_invalidates_approval"] is True
    assert len(escalation["approval_digest_fields"]) == 6

    assert value["measurement"]["stage_a"]["business_tool_execution"] is False
    assert value["measurement"]["stage_b"]["requires_independent_holdout"] is True
    assert value["measurement"]["stage_b"]["minimum_repetitions"] >= 5
    virtualization = value["virtualization"]
    assert virtualization["hyper_v_required_for_stage_a_or_b"] is False
    assert virtualization["hyper_v_must_not_be_enabled_by_this_work"] is True
    assert virtualization["future_mutating_e2e_on_host"] is False
    assert "VMware" in virtualization["future_mutating_e2e_environment"]

    erratum = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert erratum["historical_policy"] == str(POLICY.relative_to(ROOT)).replace("\\", "/")
    assert erratum["historical_artifact_edited"] is False
    assert erratum["routing_contract_changed"] is False
    assert erratum["candidate_selection_changed"] is False
    assert erratum["public_tool_count_changed"] is False
    changed_source = erratum["changed_source"]
    assert value["frozen_sources_sha256"][changed_source] == erratum["historical_source_sha256"]
    for path, expected in value["frozen_sources_sha256"].items():
        observed = (
            _blob_sha(erratum["historical_source_commit"], path)
            if path == changed_source
            else _sha(path)
        )
        assert observed == expected, path
    assert _sha("benchmarks/tool-selection/v1.6/owner-acceptance-v1.json") == (
        value["measurement"]["owner_acceptance"]["source_sha256"]
    )
    assert value["authorization"] == {
        "holdout_generator_implementation": True,
        "cloud_holdout_generation": False,
        "product_source_change": False,
        "business_tool_execution": False,
        "host_mutation": False,
    }
    print("Tool Selection v1.7 Remediation Preregistration OK - runtime locked, VMware-only future mutation")


if __name__ == "__main__":
    main()
