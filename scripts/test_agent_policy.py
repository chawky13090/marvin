"""Regressions deterministes des politiques textuelles de l'agent."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from agent_policy import autotitle_from_text, exact_tool_mentions_from_text


def main() -> int:
    assert autotitle_from_text("  corrige ce script python pour la production maintenant ") == (
        "corrige ce script python pour la…"
    )
    assert autotitle_from_text("!!!") == "Nouvelle conversation"
    names = {"file_find", "net_ping", "pc_run_powershell"}
    assert exact_tool_mentions_from_text(
        "Utilise file_find puis PC RUN POWERSHELL.", tool_names=names
    ) == {"file_find", "pc_run_powershell"}
    assert exact_tool_mentions_from_text("profile_findings", tool_names=names) == set()

    tree = ast.parse((BACKEND / "agent.py").read_text(encoding="utf-8-sig"))
    definitions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_autotitle_from_text" not in definitions
    assert "_exact_tool_mentions_from_text" not in definitions
    assert "_wants_command_text_only" not in definitions
    print("Agent Policy OK - titres, outils explicites et facade sans duplication.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
