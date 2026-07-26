"""Régressions de finalisation commune des sorties du Runner."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_turn_completion import complete_turn


class SkillOutcomes:
    def __init__(self) -> None:
        self.calls = 0

    def finalize(self, **kwargs):
        self.calls += 1
        return kwargs["encode_sse"]({"type": "skill_upgrade"})


class Runner:
    succeeded = True

    def budget_usage(self, reason):
        return {"reason": reason}


async def main() -> int:
    persisted: list[tuple] = []
    learned: list[dict] = []
    recipes: list[tuple] = []
    executed = {"calculator"}
    skill_outcomes = SkillOutcomes()

    async def finalize_answer(**_kwargs):
        return SimpleNamespace(
            content="réponse vérifiée",
            critique="correction",
            council_executed=True,
            events=[{"type": "review", "text": "revue"}],
        )

    completion = await complete_turn(
        user_query="question",
        content="réponse",
        active_model="cloud:model",
        conversation_id="conv",
        cortex_plan={"requested": {"recipe_id": "recipe"}},
        runner_state=Runner(),
        executed_tool_names=executed,
        stop_reason="criteria_satisfied",
        force_review=True,
        skill={"name": "skill", "tools": ["calculator"]},
        skill_outcomes=skill_outcomes,
        tools_spec=[],
        background_tasks=set(),
        schedule_learning=True,
        finalize_answer=finalize_answer,
        script_scanner=lambda *_args, **_kwargs: [],
        critique_pass=lambda *_args, **_kwargs: None,
        council_escalation=lambda *_args, **_kwargs: None,
        create_message=lambda *args, **kwargs: persisted.append((args, kwargs)),
        schedule_exchange_learning=lambda **kwargs: learned.append(kwargs),
        get_setting=lambda _key: "resident",
        record_recipe_outcome=lambda *args: recipes.append(args),
        build_provenance=lambda *_args, **kwargs: {
            "budget": kwargs["budget_usage"],
        },
        encode_sse=json.dumps,
    )
    event_types = [json.loads(event)["type"] for event in completion.events]
    assert event_types == ["review", "skill_upgrade", "cortex_provenance", "done"]
    assert completion.content == "réponse vérifiée"
    assert completion.critique == "correction"
    assert "ai_model_council" in executed
    assert persisted[0][0] == ("conv", "assistant", "réponse vérifiée")
    assert len(learned) == 1
    assert skill_outcomes.calls == 1
    assert recipes[0][0] == "recipe"
    provenance = json.loads(completion.events[-2])
    assert provenance["provenance"]["budget"]["reason"] == "criteria_satisfied"

    no_learning: list[dict] = []
    await complete_turn(
        user_query="question",
        content="incomplète",
        active_model="model",
        conversation_id="conv",
        cortex_plan={"requested": {}},
        runner_state=Runner(),
        executed_tool_names=set(),
        stop_reason="step_budget_exhausted",
        force_review=False,
        skill=None,
        skill_outcomes=SkillOutcomes(),
        tools_spec=[],
        background_tasks=set(),
        schedule_learning=False,
        finalize_answer=lambda **_kwargs: asyncio.sleep(
            0,
            result=SimpleNamespace(
                content="incomplète",
                critique=None,
                council_executed=False,
                events=[],
            ),
        ),
        script_scanner=lambda *_args, **_kwargs: [],
        critique_pass=lambda *_args, **_kwargs: None,
        council_escalation=lambda *_args, **_kwargs: None,
        create_message=lambda *_args, **_kwargs: None,
        schedule_exchange_learning=lambda **kwargs: no_learning.append(kwargs),
        get_setting=lambda _key: "resident",
        record_recipe_outcome=lambda *_args: (_ for _ in ()).throw(RuntimeError("db")),
        build_provenance=lambda *_args, **kwargs: {
            "budget": kwargs["budget_usage"],
        },
        encode_sse=json.dumps,
    )
    assert no_learning == []
    print("Agent Turn Completion OK - ordre, Council, apprentissage, skill et provenance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
