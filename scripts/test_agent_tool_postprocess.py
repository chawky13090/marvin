"""Régressions de post-validation des résultats d'outils."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_tool_postprocess import postprocess_tool_result


async def main() -> int:
    calls: list[tuple] = []

    def normalize(name, result, *, duration_ms):
        calls.append(("normalize", name, duration_ms))
        return {**result, "_contract": {"duration_ms": duration_ms}}

    async def critique(query, name, arguments, *, model):
        calls.append(("critique", query, name, model))
        return "action à confirmer"

    def scan(text, **options):
        calls.append(("scan", text, options))
        return ["secret potentiel"]

    processed = await postprocess_tool_result(
        tool_name="file_create_pdf",
        arguments={"content": "document"},
        result={"success": True, "requiresConfirmation": True, "message": "Prêt"},
        duration_ms=42,
        user_query="crée le PDF",
        active_model="model:cloud",
        dangerous_tools={"file_create_pdf"},
        critique_action=critique,
        scan_document=scan,
        normalize_result=normalize,
    )
    assert processed["_contract"]["duration_ms"] == 42
    assert processed["message"] == "Prêt"
    assert "secret potentiel" in processed["security_warning"]
    assert [call[0] for call in calls] == ["normalize", "scan"]

    async def broken_critique(*args, **kwargs):
        raise RuntimeError("indisponible")

    unchanged = await postprocess_tool_result(
        tool_name="calculator",
        arguments={},
        result="texte",
        duration_ms=1,
        user_query="calcul",
        active_model="local",
        dangerous_tools=set(),
        critique_action=broken_critique,
        scan_document=lambda *_args, **_kwargs: [],
        normalize_result=normalize,
    )
    assert unchanged == "texte"
    print(
        "Agent Tool Postprocess OK - contrat, critique, document et isolation des erreurs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
