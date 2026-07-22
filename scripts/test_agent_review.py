"""Regressions de la revue indépendante des réponses et actions."""

from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_review as review


async def _run() -> None:
    calls: list[dict] = []

    async def ok_generator(prompt: str, **kwargs) -> str:
        calls.append({"prompt": prompt, **kwargs})
        return "OK"

    skipped = await review.review_response(
        "question", "réponse sans code", "builder:cloud", generate=ok_generator
    )
    assert skipped is None and not calls

    with (
        patch.object(review.cloud_routing, "is_cloud_model", return_value=True),
        patch.object(
            review.cloud_routing,
            "get_cloud_config",
            return_value=(True, {"agent": "builder:cloud", "analysis": "critic:cloud"}),
        ),
    ):
        assert await review.review_response(
            "question", "réponse", "builder:cloud", force=True, generate=ok_generator
        ) is None
    assert calls[-1]["model"] == "critic:cloud"
    assert calls[-1]["timeout"] == 90

    async def finding_generator(_prompt: str, **_kwargs) -> str:
        return "- Le nom de modèle indiqué est inventé et non vérifié."

    finding = await review.review_response(
        "question", "```bash\necho ok\n```", "model", generate=finding_generator
    )
    assert finding and "inventé" in finding

    async def tiny_generator(_prompt: str, **_kwargs) -> str:
        return "-"

    assert await review.review_response(
        "question", "```text\nx\n```", "model", generate=tiny_generator
    ) is None

    async def failing_generator(_prompt: str, **_kwargs) -> str:
        raise TimeoutError("critic unavailable")

    assert await review.review_response(
        "question", "```text\nx\n```", "model", generate=failing_generator
    ) is None

    async def action_generator(prompt: str, **kwargs) -> str:
        assert "email_send" in prompt and "supprime la tâche" in prompt
        assert kwargs == {"model": "same:cloud", "timeout": 60}
        return "PROBLEME: l'action envoie un e-mail au lieu de supprimer la tâche"

    action_finding = await review.review_action(
        "supprime la tâche", "email_send", {"to": "x@example.test"},
        model="same:cloud", generate=action_generator,
    )
    assert action_finding == "l'action envoie un e-mail au lieu de supprimer la tâche"


def main() -> int:
    asyncio.run(_run())

    tree = ast.parse((BACKEND / "agent.py").read_text(encoding="utf-8-sig"))
    definitions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_run_critique_pass" not in definitions
    assert "_critique_action" not in definitions

    import agent

    assert callable(agent._run_critique_pass)
    assert callable(agent._critique_action)
    print("Agent Review OK - réponse, action, modèle distinct et façade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
