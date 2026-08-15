"""Second authorized generation attempt with a larger author pool, unchanged gates."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import generate_tool_selection_v15_holdout as generator


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.5/holdout-generation-freeze-r2.json"


def _author_items(value: dict, intent: str) -> list[dict[str, str]]:
    output = []
    for row in value.get("items") if isinstance(value.get("items"), list) else []:
        if not isinstance(row, dict) or str(row.get("intent") or "") != intent:
            continue
        prompt = " ".join(str(row.get("prompt") or "").split())
        if 20 <= len(prompt) <= 400 and not any(
            pattern.search(prompt) for pattern in generator.shared.PERSONAL_PATTERNS
        ):
            output.append({"intent": intent, "prompt": prompt})
    if len(output) < 16:
        raise RuntimeError(f"Auteur r2 insuffisant pour {intent}: {len(output)}")
    return output[:20]


async def run() -> dict:
    original_chat = generator.shared._chat

    async def larger_pool_chat(model: str, system: str, user: str, *, seed: int):
        if "Produis exactement 12 demandes" in user:
            user = user.replace("Produis exactement 12 demandes", "Produis exactement 20 demandes")
        return await original_chat(model, system, user, seed=seed + 100)

    generator.POLICY = POLICY
    generator._author_items = _author_items
    generator.shared._chat = larger_pool_chat
    try:
        return await generator.run()
    finally:
        generator.shared._chat = original_chat


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run())["counts"], ensure_ascii=False, separators=(",", ":")))
