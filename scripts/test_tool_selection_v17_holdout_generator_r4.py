"""Canaries for the bounded r4 holdout review wrapper; no Cloud call is made."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_tool_selection_v17_holdout_r4 as runner


async def _exercise() -> None:
    original = runner._ORIGINAL_CHAT
    calls: list[tuple[str, int, int]] = []

    async def fake_chat(model: str, system: str, user: str, *, seed: int):
        parsed = runner._review_payload(user)
        assert parsed is not None
        _, rows = parsed
        intents = {str(row["intent"]) for row in rows}
        assert len(intents) == 1
        intent = next(iter(intents))
        calls.append((intent, len(rows), seed))
        return {
            "items": [{"id": row["id"], "valid": True} for row in rows]
        }, {"observed_model": model}

    runner._ORIGINAL_CHAT = fake_chat
    try:
        rows = []
        for intent in runner.r3.INTENTS:
            rows.extend(
                {"id": f"{intent}-{index}", "intent": intent, "consensus_calls": []}
                for index in range(3)
            )
        response, metadata = await runner._bounded_reviews(
            "critic-model",
            "Tu révises sans corriger. JSON strict sans Markdown.",
            "Contrat immuable.\nITEMS:\n" + json.dumps(rows),
            seed=400,
        )
        assert len(response["items"]) == 3 * len(runner.r3.INTENTS)
        assert metadata["review_batching"] == "one_request_per_intent"
        assert metadata["batch_count"] == len(runner.r3.INTENTS)
        assert [item[0] for item in calls] == list(runner.r3.INTENTS)
        assert [item[2] for item in calls] == list(range(400, 400 + len(calls)))

        malformed = [{"id": "x", "intent": next(iter(runner.r3.INTENTS))}]
        try:
            await runner._bounded_reviews(
                "critic-model",
                "Tu révises sans corriger.",
                "Contrat.\nITEMS:\n" + json.dumps(malformed),
                seed=500,
            )
        except ValueError as exc:
            assert "exactement" in str(exc)
        else:
            raise AssertionError("Une revue partielle doit échouer fermée.")
    finally:
        runner._ORIGINAL_CHAT = original


if __name__ == "__main__":
    asyncio.run(_exercise())
    print("Tool Selection v1.7 Holdout Generator r4 OK - reviews bounded, partial batches denied")
