"""Hooks d'observabilité best-effort du Runner agentique Marvin.

Une panne de métrique ou d'apprentissage ne doit jamais transformer une action déjà exécutée
en échec utilisateur. Chaque destination est donc isolée, tout en conservant un ordre stable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import audit
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


async def record_tool_observation(observation: ToolObservation) -> None:
    """Diffuse une observation vers les quatre consommateurs historiques."""
    try:
        audit.log_action(
            observation.tool_name,
            observation.arguments,
            observation.result,
            source="chat",
        )
    except Exception:
        pass

    try:
        db.log_execution(
            observation.tool_name,
            observation.arguments,
            observation.result,
            observation.duration_ms,
            conversation_id=observation.conversation_id,
        )
    except Exception:
        pass

    try:
        mission_os.record_action(
            conversation_id=observation.conversation_id,
            tool_name=observation.tool_name,
            arguments=observation.arguments,
            result=observation.result,
            duration_ms=observation.duration_ms,
        )
    except Exception:
        pass

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
        except Exception:
            pass


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
