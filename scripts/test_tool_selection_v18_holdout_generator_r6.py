"""Offline positive and negative canaries for the text-only r6 review boundary."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_tool_selection_v18_holdout_r6 as runner


async def _exercise() -> None:
    observed: dict[str, object] = {}

    async def fake_cloud(model: str, system: str, user: str, *, seed: int):
        observed.update(model=model, system=system, user=user, seed=seed)
        rows = json.loads(user.rsplit("\nITEMS:\n", 1)[1])
        return {"items": [{"id": row["id"], "valid": True} for row in rows]}, {"fake": True}

    source = "prefix\nITEMS:\n" + json.dumps([{
        "id": "generic-1",
        "intent": "software.install",
        "prompt": "Installe le lecteur public choisi",
        "consensus_calls": [{"tool": "winget_install", "action": None}],
    }])
    original = runner._CLOUD_CHAT
    runner._CLOUD_CHAT = fake_cloud
    try:
        response, metadata = await runner._contract_or_cloud_chat(
            "reviewer-cloud",
            "Tu révises sans corriger. JSON strict sans Markdown.",
            source,
            seed=42,
        )
    finally:
        runner._CLOUD_CHAT = original
    assert response == {"items": [{"id": "generic-1", "valid": True}]}
    assert metadata["review_scope"] == "text_intent_and_single_action_only"
    rendered = str(observed["system"]) + str(observed["user"])
    for forbidden in ("consensus_calls", "accepted_calls", "winget_", "TOOLS_SPEC", "CATALOGUE"):
        assert forbidden not in rendered
    assert set(json.loads(str(observed["user"]).rsplit("\nITEMS:\n", 1)[1])[0]) == {
        "id", "intent", "prompt"
    }

    for invalid in ("missing marker", "x\nITEMS:\n[]", "x\nITEMS:\n[{}]"):
        try:
            runner._text_only_review_payload(invalid)
        except (ValueError, json.JSONDecodeError):
            pass
        else:
            raise AssertionError("Une revue r6 incomplète doit échouer fermé.")


def main() -> None:
    asyncio.run(_exercise())
    print("Tool Selection v1.8 Holdout Generator r6 OK - text-only scope, forbidden data stripped")


if __name__ == "__main__":
    main()
