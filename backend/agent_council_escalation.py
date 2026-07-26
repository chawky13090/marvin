"""Escalade Council bornée après désaccord d'une revue indépendante."""

from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable


async def escalate_council_on_disagreement(
    critique_text: str | None,
    answer: str,
    *,
    cortex_plan: dict[str, Any],
    user_query: str,
    council_tool: Callable[[dict[str, Any]], Awaitable[Any]],
    call_id_factory: Callable[[], str] | None = None,
) -> tuple[str, dict[str, str], Any, str] | None:
    """Appelle Council uniquement si la politique explicite l'exige après désaccord."""
    if not critique_text:
        return None
    if "review" not in cortex_plan.get("explicit_axes", []):
        return None
    if cortex_plan["resolved"]["review"] != "council_if_disagreement":
        return None

    make_call_id = call_id_factory or (
        lambda: f"cortex-council-{uuid.uuid4().hex[:10]}"
    )
    call_id = make_call_id()
    arguments = {
        "question": user_query,
        "evidence": (
            "Réponse initiale :\n"
            + answer[:5000]
            + "\n\nDésaccord du vérificateur :\n"
            + critique_text[:1800]
        ),
    }
    try:
        result = await council_tool(arguments)
    except Exception as exc:
        result = {"error": f"Escalade Council impossible : {exc}"}

    final_answer = result.get("answer") if isinstance(result, dict) else None
    block = (
        "\n\n---\n🏛️ **Arbitrage Council 5 déclenché par désaccord**\n"
        + final_answer
        if final_answer
        else ""
    )
    return call_id, arguments, result, block
