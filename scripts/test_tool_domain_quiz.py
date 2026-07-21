"""Regressions du premier domaine extrait de tools.py."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tools
from tool_domains import quiz


def _check_tools_facade() -> None:
    assert tools.execute_quiz_next is quiz.next_card
    assert tools.execute_quiz_answer is quiz.answer
    assert tools.execute_quiz_stats is quiz.stats
    assert tools.TOOLS_REGISTRY["quiz_generate"] is tools.execute_quiz_generate
    assert tools.TOOLS_REGISTRY["quiz_next"] is quiz.next_card
    assert tools.TOOLS_REGISTRY["quiz_answer"] is quiz.answer
    assert tools.TOOLS_REGISTRY["quiz_stats"] is quiz.stats


async def _check_generation() -> None:
    generate_text = AsyncMock(
        return_value=(
            'Préambule [{"question":"Couche routage ?","answer":"Couche 3"},'
            '{"question":"Protocole ?","answer":"IP"}] fin'
        )
    )
    create = Mock(side_effect=lambda topic, question, answer: {
        "topic": topic,
        "question": question,
        "answer": answer,
    })
    with patch.object(quiz.db, "create_flashcard", create):
        result = await quiz.generate(
            {"topic": "OSI", "count": 2, "model": "model:cloud"}, generate_text
        )
    assert result["success"] is True and result["count"] == 2
    assert create.call_count == 2
    assert generate_text.await_args.kwargs == {"model": "model:cloud", "timeout": 90}
    invalid = await quiz.generate({"topic": "OSI", "count": "non-entier"}, generate_text)
    assert "count" in invalid["error"]


async def _check_review_cycle() -> None:
    card = {"id": "f1", "topic": "OSI", "question": "Question", "answer": "Réponse"}
    with patch.object(quiz.db, "get_next_flashcard", return_value=card):
        next_result = await quiz.next_card({"topic": "OSI"})
    assert next_result["card"] == {"id": "f1", "topic": "OSI", "question": "Question"}
    with patch.object(
        quiz.db,
        "answer_flashcard",
        return_value={"answer": "Réponse", "interval_days": 4},
    ):
        answer_result = await quiz.answer({"id": "f1", "correct": True})
    assert answer_result["correct_answer"] == "Réponse"
    assert answer_result["next_review_in_days"] == 4
    with patch.object(quiz.db, "flashcard_stats", return_value=[{"topic": "OSI", "due_now": 2}]):
        stats_result = await quiz.stats({})
    assert "2 fiche(s) due(s)" in stats_result["message"]


def main() -> int:
    _check_tools_facade()
    asyncio.run(_check_generation())
    asyncio.run(_check_review_cycle())
    print("Tool Domain Quiz OK - facade, generation validee et cycle de revision.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
