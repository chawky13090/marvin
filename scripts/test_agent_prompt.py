"""Regressions du constructeur de prompt systeme de Marvin."""

from __future__ import annotations

import ast
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from agent_prompt import build_system_prompt


def main() -> int:
    fake_home = str(Path("C:/Users/TestMarvin"))
    with patch("agent_prompt.os.path.expanduser", return_value=fake_home):
        standard = build_system_prompt(
            [{"content": "Les reponses doivent rester concises."}], permission_level=2,
            now=datetime(2026, 7, 22, 12, 0),
        )
        secure = build_system_prompt([], permission_level=1)
        expert = build_system_prompt([], permission_level=3)
        unknown = build_system_prompt([], permission_level=999)

    for prompt in (standard, secure, expert, unknown):
        assert "Tu es Marvin" in prompt
        assert "RÈGLES D'OR ANTI-ERREUR" in prompt
        assert "RESTE SUR LA DEMANDE INITIALE" in prompt
        assert "CODE WORKSPACE ET TESTS" in prompt
        assert fake_home in prompt
        assert str(Path(fake_home) / "Desktop") in prompt

    assert "MÉMOIRE PERSONNELLE" in standard
    assert "Date actuelle : mercredi 22 juillet 2026" in standard
    assert "Les reponses doivent rester concises." in standard
    assert "STANDARD (confirmation requise)" in standard
    assert "SÉCURISÉ (lecture seule)" in secure
    assert "INTERDIT : écrire/modifier/supprimer" in secure
    assert "EXPERT (accès total)" in expert
    assert "STANDARD (confirmation requise)" in unknown
    assert "MÉMOIRE PERSONNELLE" not in secure

    tree = ast.parse((BACKEND / "agent.py").read_text(encoding="utf-8-sig"))
    definitions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_build_system_prompt" not in definitions

    import agent

    assert agent._build_system_prompt([], 2).startswith("Tu es Marvin")
    print("Agent Prompt OK - permissions, chemins, memoire, regles et facade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
