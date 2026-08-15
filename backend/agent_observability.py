"""Hooks d'observabilité du Runner agentique Marvin.

Une panne d'observation ne doit jamais faire rejouer une action déjà exécutée. Les destinations
restent isolées, mais le Runner reçoit désormais un reçu explicite : l'absence de preuve métier
durable n'est plus silencieuse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import audit
import bug_log
import database as db
import mission_os
import tool_router


@dataclass(frozen=True, slots=True)
class ToolObservation:
    conversation_id: str | None
    user_query: str
    tool_name: str
    arguments: dict[str, Any]
    result: Any
    duration_ms: int
    request_id: str | None = None
    already_observed: bool = False
    execution_id: str | None = None


@dataclass(frozen=True, slots=True)
class ObservationReceipt:
    audit_recorded: bool
    execution_recorded: bool
    evidence_recorded: bool
    routing_learned: bool
    evidence_sequence: int | None = None
    evidence_hash: str | None = None
    errors: tuple[str, ...] = ()
    execution_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        """Projette un reçu sans exception interne ni donnée métier sensible."""
        return {
            "status": "verified" if self.evidence_recorded else "unavailable",
            "proof_recorded": self.evidence_recorded,
            "sequence": self.evidence_sequence,
            "record_hash": self.evidence_hash,
            "audit_recorded": self.audit_recorded,
            "execution_recorded": self.execution_recorded,
            "execution_id": self.execution_id,
            "routing_learned": self.routing_learned,
            "warnings": list(self.errors),
            "action_must_not_be_retried": not self.evidence_recorded,
        }


async def record_tool_observation(observation: ToolObservation) -> ObservationReceipt:
    """Diffuse une observation et retourne l'état exact de chaque destination."""
    errors: list[str] = []
    audit_recorded = False
    execution_recorded = False
    evidence_recorded = False
    routing_learned = False
    evidence_sequence: int | None = None
    evidence_hash: str | None = None

    execution_id = observation.execution_id
    if observation.already_observed:
        audit_recorded = True
        execution_recorded = True
    else:
        try:
            audit.log_action(
                observation.tool_name,
                observation.arguments,
                observation.result,
                source="chat",
                request_id=observation.request_id,
            )
            audit_recorded = True
        except Exception as exc:
            errors.append(f"audit:{type(exc).__name__}")

        try:
            execution_receipt = db.log_execution(
                observation.tool_name,
                observation.arguments,
                observation.result,
                observation.duration_ms,
                conversation_id=observation.conversation_id,
                request_id=observation.request_id,
            )
            if isinstance(execution_receipt, dict):
                execution_id = str(execution_receipt.get("id") or "") or None
            execution_recorded = True
        except Exception as exc:
            errors.append(f"execution:{type(exc).__name__}")

    try:
        proof = mission_os.record_action(
            conversation_id=observation.conversation_id,
            tool_name=observation.tool_name,
            arguments=observation.arguments,
            result=observation.result,
            duration_ms=observation.duration_ms,
        )
        if isinstance(proof, dict):
            sequence = proof.get("evidence_sequence")
            record_hash = proof.get("evidence_hash")
            if (
                isinstance(sequence, int)
                and sequence > 0
                and isinstance(record_hash, str)
                and len(record_hash) == 64
                and all(character in "0123456789abcdef" for character in record_hash.lower())
            ):
                evidence_recorded = True
                evidence_sequence = sequence
                evidence_hash = record_hash
            else:
                errors.append("evidence:invalid_receipt")
        else:
            errors.append("evidence:invalid_receipt")
    except Exception as exc:
        errors.append(f"evidence:{type(exc).__name__}")

    if (
        isinstance(observation.result, dict)
        and not observation.result.get("error")
        and observation.user_query
    ):
        try:
            await tool_router.record_success(
                observation.user_query,
                observation.tool_name,
            )
            routing_learned = True
        except Exception as exc:
            errors.append(f"routing:{type(exc).__name__}")

    return ObservationReceipt(
        audit_recorded=audit_recorded,
        execution_recorded=execution_recorded,
        evidence_recorded=evidence_recorded,
        routing_learned=routing_learned,
        evidence_sequence=evidence_sequence,
        evidence_hash=evidence_hash,
        errors=tuple(errors),
        execution_id=execution_id,
    )


def record_long_chain(user_query: str, tool_count: int) -> None:
    """Journalise une seule alerte de fiabilité composée, à la demande du RunnerState."""
    try:
        audit.log_action(
            "_long_tool_chain",
            {"count": tool_count, "query": (user_query or "")[:200]},
            {
                "note": (
                    "Chaîne d'outils longue — la fiabilité composée se dégrade "
                    "au-delà de 8 appels."
                )
            },
            source="chat",
        )
    except Exception:
        pass


def record_empty_model_response(
    *,
    conversation_id: str | None,
    model: str,
    required_tool_count: int,
    executed_tool_count: int,
) -> None:
    """Trace l'absence de réponse sans conserver la demande ni les résultats."""
    bug_log.log_bug(
        "empty_model_response",
        "Le modèle n'a produit ni texte ni appel d'outil après une relance bornée.",
        context={
            "model": str(model)[:200],
            "required_tool_count": max(0, int(required_tool_count)),
            "executed_tool_count": max(0, int(executed_tool_count)),
        },
        conversation_id=conversation_id,
    )
