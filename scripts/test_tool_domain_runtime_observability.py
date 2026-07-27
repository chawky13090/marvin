"""Régressions du domaine d'observabilité runtime."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import runtime_observability


class FakeBugs:
    calls: list[tuple[int, str | None]] = []

    @classmethod
    def recent(cls, *, limit: int, kind: str | None):
        cls.calls.append((limit, kind))
        return [{"kind": kind or "tool_exception", "traceback": "trace"}]


class FakeSkills:
    calls: list[tuple[str | None, int]] = []

    @classmethod
    def get_learning_log_for_llm(cls, *, skill_name, limit):
        cls.calls.append((skill_name, limit))
        return "résumé"

    @staticmethod
    def get_learning_log(*, limit, skill_name):
        return [{"skill": skill_name, "limit": limit}]


async def main() -> None:
    bugs = await runtime_observability.bug_log_list(
        {"limit": 999, "kind": "TOOL_EXCEPTION"}, bug_runtime=FakeBugs
    )
    assert bugs["success"] is True
    assert FakeBugs.calls[-1] == (100, "tool_exception")

    invalid_kind = await runtime_observability.bug_log_list(
        {"kind": "other"}, bug_runtime=FakeBugs
    )
    assert "error" in invalid_kind

    learning = await runtime_observability.skill_learning_log(
        {"skill": " réseau ", "limit": "bad"}, skills_runtime=FakeSkills
    )
    assert learning["summary"] == "résumé"
    assert FakeSkills.calls[-1] == ("réseau", 10)

    too_long = await runtime_observability.skill_learning_log(
        {"skill": "x" * 161}, skills_runtime=FakeSkills
    )
    assert "error" in too_long
    assert tools.TOOLS_REGISTRY["bug_log_list"] is tools.execute_bug_log_list
    assert (
        tools.TOOLS_REGISTRY["skill_learning_log"]
        is tools.execute_skill_learning_log
    )


if __name__ == "__main__":
    asyncio.run(main())
    print("OK - observabilité runtime")
