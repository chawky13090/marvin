"""Regressions de la selection bornee des outils visibles par le LLM."""

from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_tool_selection as selection


def _names(specs: list[dict]) -> list[str]:
    return [spec["function"]["name"] for spec in specs]


def _spec(name: str) -> dict:
    return {"type": "function", "function": {"name": name}}


async def _route_empty(_text: str) -> dict:
    return {"semantic": set(), "learned": set()}


def main() -> int:
    empty_router = SimpleNamespace(route_tools=_route_empty)
    with patch.dict(sys.modules, {"tool_router": empty_router}), patch.object(
        selection.db, "get_setting", return_value="344"
    ):
        all_specs = asyncio.run(selection.filter_relevant_tools([], "agent"))
        assert all_specs is selection.TOOLS_SPEC

        web = set(_names(asyncio.run(selection.filter_relevant_tools(
            [{"role": "user", "content": "cherche sur le web la derniere version"}], "agent"
        ))))
        assert {"web_search", "web_browse", "web_research"} <= web

        workspace = set(_names(asyncio.run(selection.filter_relevant_tools(
            [{"role": "user", "content": "ouvre un code workspace pour ce projet"}], "agent"
        ))))
        assert {"code_workspace_start", "code_workspace_status", "code_workspace_control"} <= workspace

        email = set(_names(asyncio.run(selection.filter_relevant_tools(
            [{"role": "user", "content": "liste mes emails"}], "agent"
        ))))
        assert {"email_accounts", "email_list", "email_read"} <= email

        portable = set(_names(asyncio.run(selection.filter_relevant_tools(
            [{"role": "user", "content": "effectue une prévision météorologique pour Lyon"}],
            "agent",
        ))))
        assert "weather" in portable

        stable_explanation = set(_names(asyncio.run(selection.filter_relevant_tools(
            [{"role": "user", "content": "explique-moi cette technologie"}],
            "agent",
        ))))
        assert "web_research" not in stable_explanation

        powerpoint = set(_names(asyncio.run(selection.filter_relevant_tools(
            [{"role": "user", "content": "je veux une présentation en .pptx"}],
            "agent",
        ))))
        assert "pptx_create" in powerpoint
        assert not ({
            "ai_test_forge", "ai_code_forge", "code_python", "code_workspace_start"
        } & powerpoint)
        powerpoint_explanation = set(_names(asyncio.run(selection.filter_relevant_tools(
            [{"role": "user", "content": "explique le format pptx sans créer de fichier"}],
            "agent",
        ))))
        assert "pptx_create" not in powerpoint_explanation

        local_followup = set(_names(asyncio.run(selection.filter_relevant_tools(
            [
                {"role": "user", "content": "liste les dossiers présents sur mon bureau"},
                {"role": "assistant", "content": "Je n'ai pas exécuté l'action."},
                {"role": "user", "content": "tu as les outils nécessaires pourtant"},
            ],
            "agent",
        ))))
        assert {"file_list", "file_write", "pc_get_real_paths"} <= local_followup
        assert "web_research" not in local_followup

    sample = [_spec(name) for name in ("a", "b", "c", "d", "z")]
    with (
        patch.dict(sys.modules, {"tool_router": empty_router}),
        patch.object(selection, "TOOLS_SPEC", sample),
        patch.object(selection, "_ALWAYS_INCLUDE", {"z", "a"}),
        patch.object(selection, "_COMMON_TOOLS", set()),
        patch.object(selection, "_KEYWORD_TOOLS_NORM", [(('trigger',), {"d", "c", "b"})]),
        patch.object(selection, "_CAPABILITY_CATALOG", ()),
        patch.object(selection.db, "get_setting", return_value="3"),
    ):
        first = _names(asyncio.run(selection.filter_relevant_tools(
            [{"role": "user", "content": "trigger"}], "agent"
        )))
        second = _names(asyncio.run(selection.filter_relevant_tools(
            [{"role": "user", "content": "trigger"}], "agent"
        )))
        assert first == second == ["a", "b", "z"]

    tree = ast.parse((BACKEND / "agent.py").read_text(encoding="utf-8-sig"))
    definitions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assignments = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert "_filter_relevant_tools" not in definitions
    assert "_KEYWORD_TOOLS" not in assignments

    import agent

    assert callable(agent._filter_relevant_tools)
    print("Agent Tool Selection OK - domaines, plafond deterministe et facade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
