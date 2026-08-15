"""Validate the frozen chat-turn steering contract before product implementation."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/chat-steering/v1/preregistration.json"


def main() -> None:
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_before_product_change"
    assert value["product_version_before_change"] == "2.673.0"
    assert set(value["directive_kinds"]) == {"append", "redirect", "next", "stop"}
    assert value["directive_kinds"]["append"]["default_while_turn_is_active"] is True
    assert value["directive_kinds"]["stop"]["model_prompt_injection_forbidden"] is True

    states = set(value["directive_states"])
    assert states == {"received", "deferred", "applied", "rejected", "cancelled"}
    assert set(value["state_machine"]) == states
    terminal = {"applied", "rejected", "cancelled"}
    assert all(value["state_machine"][state] == [] for state in terminal)
    assert all(
        target in states
        for targets in value["state_machine"].values()
        for target in targets
    )

    identity = value["identity_and_serialization"]
    assert identity["one_active_root_turn_per_conversation_key"] is True
    assert identity["approval_continuation_joins_existing_root_turn"] is True
    assert identity["approval_continuation_never_waits_behind_its_parent"] is True
    assert identity["different_conversations_may_run_concurrently"] is True

    inflight = value["inflight_actions"]
    assert inflight["completed_receipts_are_immutable"] is True
    assert inflight["unknown_outcome_event"] == "action_outcome_unknown"
    assert inflight["unknown_outcome_never_triggers_automatic_replay"] is True
    assert value["stop_contract"]["forced_process_kill_as_generic_timeout_fallback_forbidden"] is True

    security = value["approval_security"]
    assert security["reclassify_risk_after_every_append_or_redirect"] is True
    assert security["recompute_pending_action_digest_after_every_append_or_redirect"] is True
    assert security["changed_payload_invalidates_prior_approval"] is True

    api = value["planned_api"]
    assert api["csrf_required_for_mutations"] is True
    assert api["conversation_ownership_checked_server_side"] is True
    assert len(set(value["planned_sse_events"])) == len(value["planned_sse_events"])

    privacy = value["privacy"]
    assert privacy["directive_text_is_personal_data"] is True
    assert privacy["technical_logs_forbid_directive_text"] is True
    assert "directive_text" not in privacy["technical_logs_allow"]

    bounds = value["bounds"]
    assert 1 <= bounds["maximum_directives_per_root_turn"] <= 100
    assert 1 <= bounds["maximum_text_characters_per_directive"] <= 10_000
    assert 1 <= bounds["maximum_pending_next_tasks_per_conversation"] <= 20

    activation = value["activation"]
    assert activation["implementation_authorized"] is False
    assert activation["feature_flag_default"] is False
    assert value["ui_contract"]["partial_backend_only_activation_forbidden"] is True
    assert activation["separate_versioned_authorization_required"] is True

    tests = set(value["required_tests"])
    for required in {
        "approval_continuation_cannot_deadlock",
        "unknown_mutation_outcome_is_never_replayed",
        "observed_content_cannot_steer",
        "positive_canary_normal_chat_still_works",
    }:
        assert required in tests
    assert value["security_status"] == "UNASSESSED_UNTIL_RUNTIME_NEGATIVE_TESTS"
    print("Chat Turn Steering Preregistration OK - 4 kinds, 5 states, implementation locked")


if __name__ == "__main__":
    main()
