"""Régressions de la finalisation commune des réponses agentiques."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_finalization import finalize_answer


async def main() -> int:
    calls: list[tuple] = []

    async def critique(user_query, content, model, *, force=False):
        calls.append(("critique", user_query, content, model, force))
        return "Vérification utile"

    async def council(critique_text, answer):
        calls.append(("council", critique_text, answer))
        return (
            "council-1",
            {"question": "Q"},
            {"answer": "Arbitrage"},
            "\n\nArbitrage final",
        )

    result = await finalize_answer(
        user_query="Q",
        content="Réponse",
        active_model="model:cloud",
        force_review=True,
        script_scanner=lambda _: ["commande à vérifier"],
        critique_pass=critique,
        council_escalation=council,
    )
    assert [event["type"] for event in result.events] == [
        "text",
        "text",
        "tool_start",
        "tool_end",
        "text",
    ]
    assert result.critique == "Vérification utile" and result.council_executed
    assert "commande à vérifier" in result.content
    assert "Vérification utile" in result.content
    assert result.content.endswith("Arbitrage final")
    assert calls[0][-1] is True

    async def no_critique(*args, **kwargs):
        return None

    async def no_council(*args, **kwargs):
        return None

    clean = await finalize_answer(
        user_query="Q",
        content="Réponse simple",
        active_model="local",
        force_review=False,
        script_scanner=lambda _: [],
        critique_pass=no_critique,
        council_escalation=no_council,
    )
    assert clean.content == "Réponse simple"
    assert clean.events == [] and clean.critique is None
    assert not clean.council_executed
    print("Agent Finalization OK - sécurité, critique, Council, ordre et repli.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
