"""Regressions du routage des profils, modeles et donnees sensibles."""

from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_routing as routing


class _Response:
    status_code = 200

    @staticmethod
    def json() -> dict:
        return {"models": [{"name": "qwen2.5:14b"}, {"name": "glm-5:cloud"}]}


class _Client:
    def __init__(self, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def get(self, _url: str) -> _Response:
        return _Response()


def main() -> int:
    original_cache = routing._available_models_cache.copy()
    try:
        routing._available_models_cache = set()
        assert routing.is_model_available("modele-inconnu")
        assert routing.pick_available("primaire", ["repli"]) == "primaire"

        with patch.object(routing.httpx, "AsyncClient", _Client):
            inventory = asyncio.run(routing.refresh_model_cache())
        assert inventory == {"qwen2.5:14b", "qwen2.5", "glm-5:cloud", "glm-5"}
        assert routing.is_model_available("qwen2.5:14b")
        assert routing.is_model_available("glm-5:cloud")
        assert routing.pick_available("absent:1b", ["qwen2.5:14b"]) == "qwen2.5:14b"

        routing._available_models_cache = set()
        assert routing.detect_profile([])[0] == "agent"
        assert routing.detect_profile([{"role": "user", "content": "salut"}])[0] == "chat"
        assert routing.detect_profile([{
            "role": "user", "content": "explique-moi en detail le protocole OSPF",
        }])[0] == "analysis"
        assert routing.detect_profile([{
            "role": "user", "content": "ouvre le fichier journal",
        }])[0] == "agent"
        assert routing.detect_profile([{
            "role": "user",
            "content": [
                {"type": "text", "text": "analyse"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            ],
        }])[0] == "vision"

        assert routing.is_sensitive_request(
            [{"role": "user", "content": "lis mon email"}], "lis mon email"
        )
        assert routing.is_sensitive_request([{
            "role": "assistant",
            "tool_calls": [{"function": {"name": "email_read"}}],
        }], "resume le resultat")
        assert not routing.is_sensitive_request(
            [{"role": "user", "content": "calcule 2 + 2"}], "calcule 2 + 2"
        )
    finally:
        routing._available_models_cache = original_cache

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
    for name in {
        "_refresh_model_cache", "_is_model_available", "_pick_available",
        "_is_sensitive_request", "_detect_profile",
    }:
        assert name not in definitions
    assert "_ACTION_KEYWORDS" not in assignments
    assert "_ANALYSIS_KEYWORDS" not in assignments

    import agent

    assert agent._detect_profile([{"role": "user", "content": "salut"}])[0] == "chat"
    assert callable(agent._refresh_model_cache)
    assert callable(agent._is_sensitive_tool)
    print("Agent Routing OK - inventaire, profils, sensibilite et facade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
