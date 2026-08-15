"""Validate the owner's blocking routing and autonomy acceptance contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import agent_tool_selection as selection
from tools import TOOLS_REGISTRY


CONTRACT = ROOT / "benchmarks/tool-selection/v1.6/owner-acceptance-v1.json"


def main() -> None:
    value = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_owner_language_contract_runtime_replay_pending"
    assert value["independence_claim"] is False
    assert value["generalization_score_authorized"] is False
    assert value["blocking_for_routing_regressions"] is True
    assert len(value["scenarios"]) == 5
    for scenario in value["scenarios"]:
        for key in ("required_terminal_tools", "required_initial_tools", "authorized_recovery_after_owner_confirmation"):
            for tool in scenario.get(key, []):
                assert tool in TOOLS_REGISTRY, (scenario["id"], tool)
    assert selection._software_intent_boundary("verifie les mise a jour du pc") == "software.updates_check"
    assert selection._software_intent_boundary("mais a jour windirstat") == "software.upgrade"
    assert selection._software_intent_boundary("mais a jour nextcloud talk") == "software.upgrade"
    cleanup = next(row for row in value["scenarios"] if row["id"] == "owner-confirmed-cleanup-001")
    assert "request_owner_confirmation_before_irreversible_deletion" in cleanup["permitted_flow"]
    assert "allow_os_uac_escalation_after_owner_confirmation" in cleanup["permitted_flow"]
    assert value["autonomy_contract"] == {
        "continue_after_recoverable_failure": True,
        "alternate_executor_allowed_after_owner_confirmation": True,
        "os_uac_keeps_owner_in_control": True,
        "exact_target_and_postcondition_required": True,
        "silent_or_unconfirmed_irreversible_action_forbidden": True,
    }
    assert value["runtime_replay"]["host_mutations_forbidden_in_automatic_gate"] is True
    assert value["runtime_replay"]["mutating_replay_requires_isolated_windows_vm"] is True
    assert all(flag is False for flag in value["privacy"].values())
    print("Tool Selection v1.6 Owner Acceptance OK - autonomy preserved, owner confirmation required, runtime replay pending")


if __name__ == "__main__":
    main()
