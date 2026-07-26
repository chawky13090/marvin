"""Enrichissements concurrents du tour : mémoire, compétence et outils."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass
class EnrichmentTasks:
    recall_task: asyncio.Task | None
    tools_task: asyncio.Task | None
    skill_task: asyncio.Task | None

    async def skill(self) -> dict[str, Any] | None:
        return await self.skill_task if self.skill_task else None

    async def learned_block(self) -> str:
        return await self.recall_task if self.recall_task else ""

    async def tools(self) -> list[dict[str, Any]]:
        return await self.tools_task if self.tools_task else []

    async def cancel_pending(self) -> None:
        pending = [
            task
            for task in (self.recall_task, self.tools_task, self.skill_task)
            if task is not None and not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def start_enrichments(
    *,
    messages: list[dict[str, Any]],
    user_query: str,
    profile_name: str,
    use_tools: bool,
    tool_suppression: str | bool | None,
    skill_matcher_text: Callable[[list[dict[str, Any]], str], str],
    filter_tools: Callable[
        [list[dict[str, Any]], str],
        Awaitable[list[dict[str, Any]]],
    ],
    recall: Callable[[str], Awaitable[Any]] | None = None,
    recall_block: Callable[[Any], str] | None = None,
    match_skill: Callable[[str], Awaitable[dict[str, Any] | None]] | None = None,
) -> EnrichmentTasks:
    """Démarre les trois enrichissements indépendants avec des replis isolés."""
    if recall is None or recall_block is None:
        import learning

        recall = recall or learning.recall
        recall_block = recall_block or learning.recall_block
    if match_skill is None:
        import skills

        match_skill = skills.match

    async def safe_recall() -> str:
        try:
            return recall_block(await recall(user_query))
        except asyncio.CancelledError:
            raise
        except Exception:
            return ""

    async def safe_filter() -> list[dict[str, Any]]:
        try:
            result = await filter_tools(messages, profile_name)
            return result if isinstance(result, list) else []
        except asyncio.CancelledError:
            raise
        except Exception:
            return []

    async def safe_skill() -> dict[str, Any] | None:
        try:
            match_text = skill_matcher_text(messages, user_query)
            result = await match_skill(match_text)
            return result if isinstance(result, dict) else None
        except asyncio.CancelledError:
            raise
        except Exception:
            return None

    return EnrichmentTasks(
        recall_task=(
            asyncio.create_task(safe_recall())
            if tool_suppression != "quiz_answer"
            else None
        ),
        tools_task=asyncio.create_task(safe_filter()) if use_tools else None,
        skill_task=asyncio.create_task(safe_skill()) if not tool_suppression else None,
    )


def inject_learned_block(
    ollama_messages: list[dict[str, Any]],
    learned_block: str,
) -> None:
    """Place le rappel sémantique dans le dernier message utilisateur s'il est textuel."""
    if not learned_block or not ollama_messages:
        return
    last_message = ollama_messages[-1]
    if last_message.get("role") != "user":
        return
    content = last_message.get("content", "")
    if not isinstance(content, str) or not content.strip():
        return
    last_message["content"] = (
        learned_block.strip()
        + "\n\n(Utilise ces informations mémorisées si elles sont pertinentes pour répondre, "
        "sans les répéter mot pour mot.)\n\n— Demande : "
        + content
    )


def assemble_tool_payload(
    selected_tools: list[dict[str, Any]],
    *,
    tools_spec: list[dict[str, Any]],
    explicit_tool_names: set[str],
    required_tool_names: set[str],
    skill: dict[str, Any] | None,
    use_tools: bool,
) -> list[dict[str, Any]]:
    """Assemble un catalogue sans doublon, avec priorités explicites et obligatoires."""
    payload = list(selected_tools)
    if explicit_tool_names and use_tools:
        explicit = [
            spec
            for spec in tools_spec
            if spec.get("function", {}).get("name") in explicit_tool_names
        ]
        if explicit:
            payload = explicit

    required = required_tool_names if use_tools else set()
    skill_tools = set(skill.get("tools") or []) if skill and use_tools else set()
    wanted = required | skill_tools
    present = {
        spec.get("function", {}).get("name")
        for spec in payload
    }
    for spec in tools_spec:
        name = spec.get("function", {}).get("name")
        if name in wanted and name not in present:
            payload.append(spec)
            present.add(name)
    return payload
