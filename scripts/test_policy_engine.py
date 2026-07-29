"""Tests déterministes du Policy Engine contextuel."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from policy_engine import (  # noqa: E402
    ApprovalEvidence,
    CapabilityManifest,
    DataClass,
    Effect,
    ExecutionEnvironment,
    PolicyAction,
    PolicyContext,
    PolicyEngine,
    Reversibility,
    RiskTier,
    Scope,
    call_digest,
)


ENGINE = PolicyEngine()


def context(
    tool: str,
    *,
    arguments=None,
    environment=ExecutionEnvironment.HOST,
    approval=None,
    permission=1,
):
    return PolicyContext(
        identity="user:test",
        tool_name=tool,
        arguments=arguments or {},
        permission_level=permission,
        environment=environment,
        source="test",
        target="test-target",
        approval=approval,
    )


def manifest(
    name: str,
    effects: set[Effect],
    *,
    scopes=None,
    data=None,
    reversibility=Reversibility.NOT_APPLICABLE,
    sandbox=False,
):
    return CapabilityManifest(
        name=name,
        effects=frozenset(effects),
        scopes=frozenset(scopes or {Scope.HOST}),
        data_classes=frozenset(data or {DataClass.PUBLIC}),
        reversibility=reversibility,
        idempotent=True,
        sandbox_required=sandbox,
        verified=True,
    )


def main() -> None:
    read = manifest("docker_list", {Effect.PUBLIC_READ})
    decision = ENGINE.evaluate(read, context("docker_list"), now=100)
    assert decision.action is PolicyAction.ALLOW
    assert decision.risk_tier is RiskTier.L1_READ

    missing = ENGINE.evaluate(None, context("unknown"), now=100)
    assert missing.action is PolicyAction.DENY
    assert missing.reason_code == "capability_manifest_missing"

    unverified = CapabilityManifest(
        name="legacy_tool",
        effects=frozenset({Effect.UNKNOWN}),
        scopes=frozenset({Scope.UNKNOWN}),
    )
    decision = ENGINE.evaluate(unverified, context("legacy_tool"), now=100)
    assert decision.action is PolicyAction.DENY

    sandbox_shell = manifest(
        "sandbox_shell",
        {Effect.CODE_EXECUTION},
        scopes={Scope.WORKSPACE},
        reversibility=Reversibility.FULL,
        sandbox=True,
    )
    denied = ENGINE.evaluate(
        sandbox_shell,
        context("sandbox_shell", environment=ExecutionEnvironment.HOST),
        now=100,
    )
    assert denied.reason_code == "required_isolation_missing"
    allowed = ENGINE.evaluate(
        sandbox_shell,
        context("sandbox_shell", environment=ExecutionEnvironment.SANDBOX),
        now=100,
    )
    assert allowed.action is PolicyAction.ALLOW

    send = manifest(
        "email_send",
        {Effect.EXTERNAL_COMMUNICATION},
        scopes={Scope.EXTERNAL_ACCOUNT},
        data={DataClass.PERSONAL},
        reversibility=Reversibility.NONE,
    )
    pending_context = context("email_send", arguments={"to": "test@example.invalid"})
    pending = ENGINE.evaluate(send, pending_context, now=100)
    assert pending.action is PolicyAction.REQUIRE_APPROVAL

    wrong_approval = ApprovalEvidence(
        call_digest="0" * 64,
        approved_by="user:test",
        expires_at=200,
        approval_id="approval-1",
    )
    still_pending = ENGINE.evaluate(
        send,
        context(
            "email_send",
            arguments={"to": "test@example.invalid"},
            approval=wrong_approval,
        ),
        now=100,
    )
    assert still_pending.action is PolicyAction.REQUIRE_APPROVAL

    digest = call_digest(pending_context)
    approval = ApprovalEvidence(
        call_digest=digest,
        approved_by="user:test",
        expires_at=200,
        approval_id="approval-2",
    )
    approved = ENGINE.evaluate(
        send,
        context(
            "email_send",
            arguments={"to": "test@example.invalid"},
            approval=approval,
        ),
        now=100,
    )
    assert approved.action is PolicyAction.ALLOW

    changed = ENGINE.evaluate(
        send,
        context(
            "email_send",
            arguments={"to": "other@example.invalid"},
            approval=approval,
        ),
        now=100,
    )
    assert changed.action is PolicyAction.REQUIRE_APPROVAL

    expired = ApprovalEvidence(
        call_digest=digest,
        approved_by="user:test",
        expires_at=99,
        approval_id="approval-3",
    )
    expired_decision = ENGINE.evaluate(
        send,
        context(
            "email_send",
            arguments={"to": "test@example.invalid"},
            approval=expired,
        ),
        now=100,
    )
    assert expired_decision.action is PolicyAction.REQUIRE_APPROVAL

    print("OK - politique contextuelle, isolation et approbations liées aux arguments")


if __name__ == "__main__":
    main()
