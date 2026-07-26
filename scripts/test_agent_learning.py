"""Régressions de la planification d'apprentissage post-réponse."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_learning import schedule_exchange_learning


async def main() -> int:
    calls: list[tuple] = []

    async def generate(prompt, *, model, timeout):
        calls.append(("generate", prompt, model, timeout))
        return "faits"

    async def learn(user_query, final_content, teacher):
        calls.append(("learn", user_query, final_content))
        assert await teacher("prompt") == "faits"

    resident_tasks: set[asyncio.Task] = set()
    resident = schedule_exchange_learning(
        user_query="question",
        final_content="réponse",
        active_model="resident:model",
        background_tasks=resident_tasks,
        get_setting=lambda _name: "resident",
        learn_from_exchange=learn,
        generate=generate,
    )
    assert resident is not None and resident in resident_tasks
    await resident
    await asyncio.sleep(0)
    assert resident not in resident_tasks
    assert calls[-1] == ("generate", "prompt", "resident:model", 180)

    dedicated_tasks: set[asyncio.Task] = set()
    dedicated = schedule_exchange_learning(
        user_query="question",
        final_content="réponse",
        active_model="ignored:model",
        background_tasks=dedicated_tasks,
        get_setting=lambda _name: "dedicated",
        learn_from_exchange=learn,
        generate=generate,
    )
    assert dedicated is not None
    await dedicated
    assert calls[-1] == ("generate", "prompt", None, 180)

    fallback_tasks: set[asyncio.Task] = set()
    fallback = schedule_exchange_learning(
        user_query="question",
        final_content="réponse",
        active_model="fallback:model",
        background_tasks=fallback_tasks,
        get_setting=lambda _name: (_ for _ in ()).throw(RuntimeError("db")),
        learn_from_exchange=learn,
        generate=generate,
    )
    assert fallback is not None
    await fallback
    assert calls[-1] == ("generate", "prompt", "fallback:model", 180)

    print("Agent Learning OK - résident, dédié, repli et suivi anti-GC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
