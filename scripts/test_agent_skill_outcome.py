"""Régressions de finalisation idempotente des compétences du Runner."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_skill_outcome import SkillOutcomeRecorder


class FakeSkills:
    def __init__(self) -> None:
        self.outcomes: list[tuple] = []
        self.successes: list[tuple] = []
        self.upgrades: list[tuple] = []

    def record_outcome(self, *args, **kwargs) -> None:
        self.outcomes.append((args, kwargs))

    def record_success_trace(self, *args, **kwargs) -> None:
        self.successes.append((args, kwargs))

    async def upgrade_skill(self, *args, **kwargs) -> None:
        self.upgrades.append((args, kwargs))


class FakeTools:
    async def _ollama_generate(self, prompt, *, model, timeout):
        return f"{prompt}:{model}:{timeout}"


def state(*, succeeded: bool) -> SimpleNamespace:
    return SimpleNamespace(
        tool_count=2,
        failed_tools=0 if succeeded else 1,
        succeeded=succeeded,
        successful_tools=2 if succeeded else 1,
        successful_calls=[{"name": "calculator"}],
        trace=["calculator: ok", "document_generate: failed"],
    )


async def main() -> int:
    skill = {"name": "diagnostic", "tools": ["calculator"]}
    tools_spec = [{"function": {"name": "calculator"}}]

    successful_skills = FakeSkills()
    success_recorder = SkillOutcomeRecorder()
    first = success_recorder.finalize(
        skill=skill,
        runner_state=state(succeeded=True),
        user_query="diagnostique",
        final_content="terminé",
        tools_spec=tools_spec,
        background_tasks=set(),
        encode_sse=json.dumps,
        skills_module=successful_skills,
        tools_module=FakeTools(),
    )
    assert first is None
    assert len(successful_skills.outcomes) == 1
    assert len(successful_skills.successes) == 1
    assert success_recorder.finalize(
        skill=skill,
        runner_state=state(succeeded=True),
        user_query="diagnostique",
        final_content="terminé",
        tools_spec=tools_spec,
        background_tasks=set(),
        encode_sse=json.dumps,
        skills_module=successful_skills,
        tools_module=FakeTools(),
    ) is None
    assert len(successful_skills.outcomes) == 1

    failed_skills = FakeSkills()
    failed_tasks: set[asyncio.Task] = set()
    failure_event = SkillOutcomeRecorder().finalize(
        skill=skill,
        runner_state=state(succeeded=False),
        user_query="diagnostique",
        final_content="échec",
        tools_spec=tools_spec,
        background_tasks=failed_tasks,
        encode_sse=json.dumps,
        skills_module=failed_skills,
        tools_module=FakeTools(),
    )
    assert json.loads(failure_event)["type"] == "skill_upgrade"
    await asyncio.gather(*tuple(failed_tasks))
    assert len(failed_skills.outcomes) == 1
    assert len(failed_skills.upgrades) == 1
    assert failed_skills.upgrades[0][1]["tool_names"] == ["calculator"]

    assert SkillOutcomeRecorder().finalize(
        skill=None,
        runner_state=state(succeeded=True),
        user_query="",
        final_content="",
        tools_spec=[],
        background_tasks=set(),
        encode_sse=json.dumps,
    ) is None
    print("Agent Skill Outcome OK - succès, échec, idempotence et auto-amélioration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
