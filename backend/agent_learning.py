"""Planification de l'apprentissage durable après une réponse du Runner."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable


def schedule_exchange_learning(
    *,
    user_query: str,
    final_content: str,
    active_model: str,
    background_tasks: set[asyncio.Task],
    get_setting: Callable[[str], Any],
    learn_from_exchange: Callable[
        [str, str, Callable[[str], Awaitable[str]]],
        Awaitable[Any],
    ]
    | None = None,
    generate: Callable[..., Awaitable[str]] | None = None,
) -> asyncio.Task | None:
    """Programme l'apprentissage sans bloquer la réponse et conserve la tâche anti-GC."""
    try:
        if learn_from_exchange is None:
            import learning

            learn_from_exchange = learning.learn_from_exchange
        if generate is None:
            import tools

            generate = tools._ollama_generate

        try:
            strategy = get_setting("learn_strategy") or "resident"
        except Exception:
            strategy = "resident"
        learn_model = None if strategy == "dedicated" else active_model

        async def teacher(prompt: str) -> str:
            return await generate(prompt, model=learn_model, timeout=180)

        task = asyncio.create_task(
            learn_from_exchange(user_query, final_content, teacher)
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        return task
    except Exception:
        return None
