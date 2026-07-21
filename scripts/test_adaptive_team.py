"""Régressions déterministes Adaptive Team Runtime, sans appel cloud."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import adaptive_team
import cortex


async def exercise_runtime() -> None:
    swarm_result = {
        "success": True,
        "answer": "Dossier de recherche sourcé.",
        "models_consulted": ["research:cloud"],
        "families": ["research"],
        "evidence_fabric": {
            "claim_count": 2,
            "epistemic_debt": {"score": 0.7},
            "semantic_verification": {
                "supported": 1, "contradicted": 0, "disputed": 0, "insufficient": 1,
            },
        },
    }
    cortex_result = {
        "success": True,
        "answer": "Décision finale vérifiée.",
        "models_consulted": ["analysis:cloud"],
        "families": ["analysis"],
    }
    with (
        patch.object(adaptive_team, "validate_runtime", return_value=None),
        patch("research_swarm.execute", new=AsyncMock(return_value=swarm_result)) as swarm,
        patch("cortex_search.execute", new=AsyncMock(return_value=cortex_result)) as search,
    ):
        result = await adaptive_team.execute(
            "Cherche les sources actuelles puis propose une architecture technique approfondie "
            "avec plusieurs stratégies et leurs compromis."
        )
    assert result["success"] is True
    assert result["answer"] == "Décision finale vérifiée."
    assert [item["name"] for item in result["stages"]] == ["research_swarm", "cortex_search"]
    assert "research:cloud" in result["models_consulted"]
    swarm.assert_awaited_once()
    search.assert_awaited_once()
    passed_evidence = search.await_args.kwargs["evidence"]
    assert "Dossier de recherche sourcé" in passed_evidence
    assert "Ne reprends pas comme fait une affirmation insuffisante" in passed_evidence
    assert "dette=0.7" in passed_evidence

    with (
        patch.object(adaptive_team, "validate_runtime", return_value=None),
        patch("research_swarm.execute", new=AsyncMock(return_value=swarm_result)),
        patch("code_forge.execute", new=AsyncMock(return_value={"error": "gate refusé", "success": False})),
    ):
        failed = await adaptive_team.execute(
            "Recherche les pratiques actuelles puis crée un script Bash d'installation sécurisé."
        )
    assert failed.get("success") is not True
    assert "livrable final" in failed["error"]


def main() -> int:
    deep = adaptive_team.plan(
        "Cherche les meilleures pratiques actuelles et conçois une architecture technique "
        "approfondie avec plusieurs alternatives."
    )
    assert deep["pipeline"] == ["research_swarm", "cortex_search"]
    assert deep["complexity"] >= 5
    assert adaptive_team.plan("Choisis entre A et B")["pipeline"] == ["model_council"]
    assert adaptive_team.should_auto_activate(
        "Fais une analyse approfondie avec plusieurs experts afin de comparer cette architecture "
        "et proposer une solution réellement robuste."
    ) is True
    assert adaptive_team.should_auto_activate("Réponds simplement bonjour.") is False

    compiled = cortex.compile_contract(
        "Cherche les sources actuelles et fais une analyse approfondie avec plusieurs experts "
        "pour comparer ces architectures techniques."
    )
    assert compiled["resolved"]["review"] == "team"
    assert compiled["forced_tools"] == ["ai_adaptive_team"]
    private = cortex.compile_contract(
        "Fais une analyse approfondie avec plusieurs experts de mon mot de passe et de mes emails."
    )
    assert "ai_adaptive_team" not in private["forced_tools"]
    explicit = cortex.compile_contract("Compare ces choix", {"review": "team"})
    assert explicit["forced_tools"] == ["ai_adaptive_team"]

    asyncio.run(exercise_runtime())
    print("Adaptive Team OK - activation prudente, pipeline recherche puis Cortex et confidentialité.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
