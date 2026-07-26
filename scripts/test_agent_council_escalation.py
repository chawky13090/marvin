"""Régressions de l'escalade Council conditionnée par une revue."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_council_escalation import escalate_council_on_disagreement


async def main() -> int:
    calls: list[dict] = []

    async def council(arguments):
        calls.append(arguments)
        return {"answer": "arbitrage"}

    explicit_plan = {
        "explicit_axes": ["review"],
        "resolved": {"review": "council_if_disagreement"},
    }
    result = await escalate_council_on_disagreement(
        "désaccord",
        "réponse",
        cortex_plan=explicit_plan,
        user_query="question",
        council_tool=council,
        call_id_factory=lambda: "cortex-council-test",
    )
    assert result is not None
    call_id, arguments, tool_result, block = result
    assert call_id == "cortex-council-test"
    assert arguments["question"] == "question"
    assert "désaccord" in arguments["evidence"]
    assert tool_result == {"answer": "arbitrage"}
    assert "arbitrage" in block
    assert len(calls) == 1

    for critique, plan in (
        (None, explicit_plan),
        ("désaccord", {"explicit_axes": [], "resolved": {"review": "council_if_disagreement"}}),
        ("désaccord", {"explicit_axes": ["review"], "resolved": {"review": "verify"}}),
    ):
        assert await escalate_council_on_disagreement(
            critique,
            "réponse",
            cortex_plan=plan,
            user_query="question",
            council_tool=council,
        ) is None
    assert len(calls) == 1

    async def broken_council(_arguments):
        raise RuntimeError("indisponible")

    failed = await escalate_council_on_disagreement(
        "désaccord",
        "réponse",
        cortex_plan=explicit_plan,
        user_query="question",
        council_tool=broken_council,
        call_id_factory=lambda: "cortex-council-error",
    )
    assert failed is not None
    assert failed[2]["error"].startswith("Escalade Council impossible")
    assert failed[3] == ""
    print("Agent Council Escalation OK - politique, bornes, succès et repli.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
