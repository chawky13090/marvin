"""Décisions d'autorisation contextuelles pour les appels d'outils Marvin.

Le moteur ne sélectionne jamais un outil. Il évalue un appel déjà proposé à partir
de ses effets déclarés, de sa cible, de l'environnement et d'une éventuelle preuve
d'approbation émise hors du contexte LLM.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any, Mapping


class Effect(StrEnum):
    PUBLIC_READ = "public_read"
    SENSITIVE_READ = "sensitive_read"
    LOCAL_WRITE = "local_write"
    INFRASTRUCTURE_WRITE = "infrastructure_write"
    EXTERNAL_COMMUNICATION = "external_communication"
    NETWORK_CHANGE = "network_change"
    PRIVILEGE_CHANGE = "privilege_change"
    CODE_EXECUTION = "code_execution"
    DELETE = "delete"
    SPEND = "spend"
    UNKNOWN = "unknown"


class Scope(StrEnum):
    CONVERSATION = "conversation"
    WORKSPACE = "workspace"
    HOST = "host"
    LAN = "lan"
    INTERNET = "internet"
    EXTERNAL_ACCOUNT = "external_account"
    UNKNOWN = "unknown"


class DataClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"
    SECRET = "secret"
    REGULATED = "regulated"
    UNKNOWN = "unknown"


class Reversibility(StrEnum):
    FULL = "full"
    COMPENSABLE = "compensable"
    PARTIAL = "partial"
    NONE = "none"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class ExecutionEnvironment(StrEnum):
    CONVERSATION = "conversation"
    SANDBOX = "sandbox"
    TEST_VM = "test_vm"
    HOST = "host"
    PRODUCTION = "production"
    UNKNOWN = "unknown"


class RiskTier(IntEnum):
    L0_INTERNAL = 0
    L1_READ = 1
    L2_REVERSIBLE = 2
    L3_OPERATIONAL = 3
    L4_SENSITIVE = 4
    L5_CRITICAL = 5


class PolicyAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    name: str
    effects: frozenset[Effect]
    scopes: frozenset[Scope]
    data_classes: frozenset[DataClass] = frozenset({DataClass.UNKNOWN})
    reversibility: Reversibility = Reversibility.UNKNOWN
    idempotent: bool = False
    sandbox_required: bool = False
    timeout_seconds: int = 30
    verified: bool = False

    def __post_init__(self) -> None:
        if not self.name or len(self.name) > 128:
            raise ValueError("Nom de capacité invalide.")
        if not self.effects or not self.scopes:
            raise ValueError("Effets et portées sont obligatoires.")
        if not 1 <= self.timeout_seconds <= 86_400:
            raise ValueError("Timeout de capacité hors limites.")


@dataclass(frozen=True, slots=True)
class ApprovalEvidence:
    call_digest: str
    approved_by: str
    expires_at: float
    approval_id: str

    def valid_for(self, digest: str, now: float) -> bool:
        return (
            bool(self.approved_by)
            and bool(self.approval_id)
            and self.call_digest == digest
            and math.isfinite(self.expires_at)
            and self.expires_at >= now
        )


@dataclass(frozen=True, slots=True)
class PolicyContext:
    identity: str
    tool_name: str
    arguments: Mapping[str, Any]
    permission_level: int
    environment: ExecutionEnvironment
    source: str
    target: str = ""
    approval: ApprovalEvidence | None = None
    request_id: str = ""
    conversation_id: str = ""


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    action: PolicyAction
    risk_tier: RiskTier
    reason_code: str
    call_digest: str
    constraints: Mapping[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.action is PolicyAction.ALLOW


def _canonical_arguments(arguments: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Arguments non sérialisables pour autorisation.") from exc


def call_digest(context: PolicyContext) -> str:
    payload = b"\x00".join(
        (
            context.identity.encode("utf-8"),
            context.tool_name.encode("utf-8"),
            context.environment.value.encode("ascii"),
            context.target.encode("utf-8"),
            _canonical_arguments(context.arguments),
        )
    )
    return hashlib.sha256(payload).hexdigest()


def risk_tier(
    manifest: CapabilityManifest,
    environment: ExecutionEnvironment,
) -> RiskTier:
    effects = manifest.effects
    data_classes = manifest.data_classes
    if effects & {Effect.DELETE, Effect.PRIVILEGE_CHANGE}:
        return RiskTier.L5_CRITICAL
    if effects & {
        Effect.EXTERNAL_COMMUNICATION,
        Effect.NETWORK_CHANGE,
        Effect.SPEND,
    }:
        return RiskTier.L4_SENSITIVE
    if DataClass.SECRET in data_classes or DataClass.REGULATED in data_classes:
        return RiskTier.L4_SENSITIVE
    if effects & {Effect.INFRASTRUCTURE_WRITE, Effect.CODE_EXECUTION}:
        if environment in {ExecutionEnvironment.SANDBOX, ExecutionEnvironment.TEST_VM}:
            return RiskTier.L2_REVERSIBLE
        return RiskTier.L3_OPERATIONAL
    if Effect.LOCAL_WRITE in effects:
        return (
            RiskTier.L2_REVERSIBLE
            if manifest.reversibility in {
                Reversibility.FULL,
                Reversibility.COMPENSABLE,
            }
            else RiskTier.L3_OPERATIONAL
        )
    if effects <= {Effect.PUBLIC_READ, Effect.SENSITIVE_READ}:
        return (
            RiskTier.L1_READ
            if effects == {Effect.PUBLIC_READ}
            and data_classes <= {DataClass.PUBLIC}
            else RiskTier.L3_OPERATIONAL
        )
    return RiskTier.L5_CRITICAL


class PolicyEngine:
    """Moteur fail-closed, indépendant du registre et du LLM."""

    def evaluate(
        self,
        manifest: CapabilityManifest | None,
        context: PolicyContext,
        *,
        now: float | None = None,
    ) -> PolicyDecision:
        digest = call_digest(context)
        if manifest is None or manifest.name != context.tool_name:
            return PolicyDecision(
                PolicyAction.DENY,
                RiskTier.L5_CRITICAL,
                "capability_manifest_missing",
                digest,
            )
        tier = risk_tier(manifest, context.environment)
        if (
            Effect.UNKNOWN in manifest.effects
            or Scope.UNKNOWN in manifest.scopes
            or not manifest.verified
        ):
            return PolicyDecision(
                PolicyAction.DENY,
                tier,
                "capability_not_verified",
                digest,
            )
        if manifest.sandbox_required and context.environment not in {
            ExecutionEnvironment.SANDBOX,
            ExecutionEnvironment.TEST_VM,
        }:
            return PolicyDecision(
                PolicyAction.DENY,
                tier,
                "required_isolation_missing",
                digest,
            )
        if context.permission_level <= 0 and tier >= RiskTier.L2_REVERSIBLE:
            return PolicyDecision(
                PolicyAction.DENY,
                tier,
                "permission_level_insufficient",
                digest,
            )

        requires_approval = tier >= RiskTier.L4_SENSITIVE or (
            tier >= RiskTier.L3_OPERATIONAL
            and context.environment
            in {ExecutionEnvironment.HOST, ExecutionEnvironment.PRODUCTION}
        )
        current_time = time.time() if now is None else now
        if requires_approval and not (
            context.approval and context.approval.valid_for(digest, current_time)
        ):
            return PolicyDecision(
                PolicyAction.REQUIRE_APPROVAL,
                tier,
                "explicit_approval_required",
                digest,
                {
                    "tool": manifest.name,
                    "target": context.target,
                    "effects": sorted(effect.value for effect in manifest.effects),
                    "expires_required": True,
                },
            )
        return PolicyDecision(
            PolicyAction.ALLOW,
            tier,
            "policy_satisfied",
            digest,
            {
                "timeout_seconds": manifest.timeout_seconds,
                "idempotent": manifest.idempotent,
            },
        )

