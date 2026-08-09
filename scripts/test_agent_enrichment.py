"""Régressions des enrichissements concurrents du Runner."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_enrichment import (
    assemble_tool_payload,
    inject_learned_block,
    start_enrichments,
)


def spec(name: str) -> dict:
    return {"type": "function", "function": {"name": name}}


async def main() -> int:
    messages = [{"role": "user", "content": "analyse"}]

    async def recall(query):
        return [query]

    async def filter_tools(_messages, _profile):
        return [spec("search")]

    async def match_skill(text):
        return {"name": "analyse", "tools": ["verify"], "text": text}

    tasks = start_enrichments(
        messages=messages,
        user_query="analyse",
        profile_name="agent",
        use_tools=True,
        tool_suppression=None,
        skill_matcher_text=lambda _messages, query: f"match:{query}",
        filter_tools=filter_tools,
        recall=recall,
        recall_block=lambda values: f"memo:{values[0]}",
        match_skill=match_skill,
    )
    assert (await tasks.skill())["text"] == "match:analyse"
    assert await tasks.learned_block() == "memo:analyse"
    selected = await tasks.tools()
    assert [item["function"]["name"] for item in selected] == ["search"]

    ollama_messages = [{"role": "user", "content": "question"}]
    inject_learned_block(ollama_messages, "mémoire")
    assert ollama_messages[0]["content"].startswith("mémoire")
    assert ollama_messages[0]["content"].endswith("question")

    payload = assemble_tool_payload(
        selected,
        tools_spec=[spec("search"), spec("verify"), spec("required")],
        explicit_tool_names=set(),
        required_tool_names={"required"},
        skill={"tools": ["verify", "required"]},
        use_tools=True,
    )
    assert [item["function"]["name"] for item in payload] == [
        "search",
        "verify",
        "required",
    ]
    explicit = assemble_tool_payload(
        selected,
        tools_spec=[spec("search"), spec("verify"), spec("required")],
        explicit_tool_names={"verify"},
        required_tool_names={"required"},
        skill={"tools": ["search"]},
        use_tools=True,
    )
    assert [item["function"]["name"] for item in explicit] == ["verify"]

    release = asyncio.Event()

    async def wait_forever(_query):
        await release.wait()
        return []

    cancellable = start_enrichments(
        messages=messages,
        user_query="analyse",
        profile_name="agent",
        use_tools=False,
        tool_suppression=None,
        skill_matcher_text=lambda _messages, query: query,
        filter_tools=filter_tools,
        recall=wait_forever,
        recall_block=lambda _values: "",
        match_skill=wait_forever,
    )
    await asyncio.sleep(0)
    await cancellable.cancel_pending()
    assert cancellable.recall_task.cancelled()
    assert cancellable.skill_task.cancelled()

    async def broken(_value):
        raise RuntimeError("indisponible")

    resilient = start_enrichments(
        messages=messages,
        user_query="analyse",
        profile_name="agent",
        use_tools=True,
        tool_suppression=None,
        skill_matcher_text=lambda _messages, query: query,
        filter_tools=broken,
        recall=broken,
        recall_block=lambda _values: "",
        match_skill=broken,
    )
    assert await resilient.learned_block() == ""
    assert await resilient.tools() == []
    assert await resilient.skill() is None
    print(
        "Agent Enrichment OK - concurrence, replis, annulation, mémoire et catalogue."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
