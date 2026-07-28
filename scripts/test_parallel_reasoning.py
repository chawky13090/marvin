"""Régressions du raisonnement parallèle borné et de ses résultats partiels."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import parallel_reasoning
import tools


async def main() -> None:
    calls: list[str] = []

    async def generator(prompt: str, **_kwargs: Any) -> dict[str, str]:
        calls.append(prompt)
        if prompt.startswith("Objectif :"):
            return {
                "text": "- Examiner l'architecture\n- Examiner les tests",
                "model": "planner:cloud",
            }
        if "Fusionne-les" in prompt:
            return {"text": "Synthèse vérifiable", "model": "synth:cloud"}
        if "Sous-tâche 1" in prompt:
            return {"text": "Architecture analysée", "model": "worker:cloud"}
        if "Sous-tâche 2" in prompt:
            raise RuntimeError("reviewer indisponible")
        raise AssertionError(prompt)

    parallel_reasoning.configure(
        generate=generator,
        id_factory=lambda: "trace-test",
    )
    result = await parallel_reasoning.run({"goal": "Consolider Marvin"})
    assert result["success"] is True
    assert result["trace_id"] == "trace-test"
    assert result["answer"] == "Synthèse vérifiable"
    assert result["partial"] is True
    assert result["failed_subtasks"] == 1
    assert result["models"] == {
        "decomposition": "planner:cloud",
        "workers": ["worker:cloud", None],
        "synthesis": "synth:cloud",
    }
    assert [item["status"] for item in result["subtask_results"]] == [
        "ok",
        "error",
    ]
    assert result["policy"]["tool_access"] is False
    assert "reviewer indisponible" not in calls[-1]

    assert "liste" in (
        await parallel_reasoning.run(
            {"goal": "But", "subtasks": "pas une liste"}
        )
    )["error"]
    assert "20000" in (
        await parallel_reasoning.run({"goal": "x" * 20_001})
    )["error"]
    assert "au moins deux" in (
        await parallel_reasoning.run({"goal": "But", "subtasks": ["Unique"]})
    )["error"]

    async def synthesis_failure(prompt: str, **_kwargs: Any) -> str:
        if "Fusionne-les" in prompt:
            raise RuntimeError("synthèse indisponible")
        return "Résultat"

    parallel_reasoning.configure(
        generate=synthesis_failure,
        id_factory=lambda: "trace-failure",
    )
    failed = await parallel_reasoning.run(
        {"goal": "But", "subtasks": ["Angle A", "Angle B"]}
    )
    assert failed["phase"] == "synthesis"
    assert failed["partial"] is True
    assert len(failed["subtask_results"]) == 2

    parallel_reasoning.configure(generate=tools._ollama_generate)
    assert tools.execute_ai_subagents_run is parallel_reasoning.run
    assert tools.TOOLS_REGISTRY["ai_subagents_run"] is parallel_reasoning.run


if __name__ == "__main__":
    asyncio.run(main())
    print("Parallel reasoning OK - bornes, trace, partiels, synthèse et façade.")
