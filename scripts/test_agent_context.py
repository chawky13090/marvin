"""Regressions du contexte de session et des captures multimodales."""

from __future__ import annotations

import ast
import asyncio
import base64
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_context as context


async def _exercise_summary() -> None:
    overflow = [
        {"role": "user", "content": "Décision importante"},
        {"role": "assistant", "content": "Décision enregistrée"},
        {"role": "tool", "content": "à ignorer"},
        {"role": "user", "content": [{"type": "text", "text": "Suite du projet"}]},
    ]
    generated: list[dict] = []

    async def generate(prompt: str, **kwargs) -> str:
        generated.append({"prompt": prompt, **kwargs})
        return "- Continuer le projet"

    with (
        patch.object(context.db, "get_setting", return_value=None),
        patch.object(context.db, "set_setting") as save,
    ):
        summary = await context.summarize_overflow(
            "conversation-1", overflow, "same:cloud", generate=generate
        )
    assert summary == "- Continuer le projet"
    assert "Décision importante" in generated[0]["prompt"]
    assert "à ignorer" not in generated[0]["prompt"]
    assert generated[0]["model"] == "same:cloud"
    save.assert_called_once_with(
        "convsum_conversation-1",
        {"covered": 4, "summary": "- Continuer le projet"},
    )

    with patch.object(
        context.db,
        "get_setting",
        return_value={"covered": 3, "summary": "résumé en cache"},
    ):
        cached = await context.summarize_overflow(
            "conversation-1", overflow, generate=generate
        )
    assert cached == "résumé en cache"
    assert len(generated) == 1

    assert await context.summarize_overflow("conversation-1", overflow[:3]) is None


async def _exercise_screenshots() -> None:
    encoded = base64.b64encode(b"fake-png-content").decode("ascii")
    data_url = f"data:image/png;base64,{encoded}"
    analyzed_paths: list[Path] = []

    async def analyze(path: str) -> dict:
        analyzed_paths.append(Path(path))
        assert Path(path).read_bytes() == b"fake-png-content"
        return {"caption": "capture", "ocr_text": "texte"}

    with tempfile.TemporaryDirectory() as temp:
        data_dir = Path(temp)
        with patch.object(
            context.db,
            "create_screenshot",
            side_effect=lambda conversation_id, path, caption, ocr_text: {
                "conversation_id": conversation_id,
                "path": path,
                "caption": caption,
                "ocr_text": ocr_text,
            },
        ):
            row = await context.persist_and_analyze_screenshot(
                "conversation-1", data_url, data_dir=data_dir, analyze=analyze
            )
        assert row and row["caption"] == "capture"
        assert analyzed_paths[0].is_file()
        assert analyzed_paths[0].parent == data_dir / "screenshots" / "conversation-1"

        rejected = await context.persist_and_analyze_screenshot(
            "../../outside", data_url, data_dir=data_dir, analyze=analyze
        )
        assert rejected is None
        assert not (data_dir.parent / "outside").exists()

        async def fail_analysis(_path: str) -> dict:
            raise RuntimeError("vision indisponible")

        failed = await context.persist_and_analyze_screenshot(
            "conversation-2", data_url, data_dir=data_dir, analyze=fail_analysis
        )
        assert failed is None
        assert list((data_dir / "screenshots" / "conversation-2").glob("*")) == []

        parts = [
            {"type": "text", "text": "bonjour"},
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "image", "url": "https://example.test/not-persisted.png"},
        ]
        assert context.screenshot_data_urls(parts) == [data_url]


def main() -> int:
    asyncio.run(_exercise_summary())
    asyncio.run(_exercise_screenshots())

    tree = ast.parse((BACKEND / "agent.py").read_text(encoding="utf-8-sig"))
    definitions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not {
        "_conversation_summary",
        "_persist_and_analyze_one_screenshot",
        "_persist_and_analyze_screenshots",
    } & definitions

    import agent

    assert callable(agent._conversation_summary)
    assert callable(agent._persist_and_analyze_one_screenshot)
    assert callable(agent._persist_and_analyze_screenshots)
    print("Agent Context OK - compaction, cache, captures, nettoyage et façade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
