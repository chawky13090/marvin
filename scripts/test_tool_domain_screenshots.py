"""Régressions déterministes du domaine Captures documentaires."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tool_domains import screenshots
import database as db
import tools


async def _run() -> None:
    rows = [
        {
            "id": "shot-1",
            "conversation_id": "conv-1",
            "path": "C:/captures/one.png",
            "caption": "Console Debian",
            "ocr_text": "apt update",
            "created_at": "2026-07-27T10:00:00",
        },
        {
            "id": "shot-2",
            "conversation_id": "conv-1",
            "path": "C:/captures/two.png",
            "caption": "",
            "ocr_text": "",
            "created_at": "2026-07-27T10:01:00",
        },
    ]
    render_calls: list[tuple[str, dict]] = []

    def list_rows(conversation_id: str | None, *, limit: int) -> list[dict]:
        assert conversation_id in {None, "conv-1"}
        return rows[:limit]

    async def create_docx(args: dict) -> dict:
        render_calls.append(("docx", args))
        return {"success": True, "path": args["path"]}

    async def create_pdf(args: dict) -> dict:
        render_calls.append(("pdf", args))
        return {"success": True, "path": args["path"]}

    requests: list[dict] = []

    async def requester(
        method: str, path: str, *, timeout: float, payload: dict | None = None
    ) -> dict:
        assert method == "POST"
        assert path == "/api/generate"
        assert timeout == 60
        requests.append(payload or {})
        return {
            "response": (
                "LÉGENDE: Fenêtre de terminal Debian\n"
                "TEXTE RELEVÉ: apt update\nLecture des paquets"
            )
        }

    screenshots.configure(
        list_screenshots=list_rows,
        ollama_url="http://127.0.0.1:11434",
        requester=requester,
    )
    screenshots.configure_renderers(create_docx=create_docx, create_pdf=create_pdf)

    listed = await screenshots.list_for_conversation(
        {"conversation_id": "conv-1", "limit": 2}
    )
    assert listed.get("success") is True, listed
    assert listed["count"] == 2
    assert set(listed["screenshots"][0]) == {
        "id", "path", "caption", "ocr_text", "created_at"
    }
    invalid_limit = await screenshots.list_for_conversation({"limit": 0})
    assert invalid_limit.get("success") is True  # zéro conserve la valeur par défaut historique
    too_large = await screenshots.list_for_conversation({"limit": 501})
    assert "compris entre" in too_large.get("error", "")

    generated = await screenshots.generate_document(
        {
            "conversation_id": "conv-1",
            "format": "pdf",
            "path": "C:/exports/report.pdf",
            "title": "Rapport captures",
            "intro": "Contexte",
        }
    )
    assert generated.get("success") is True, generated
    assert generated["screenshots_used"] == 2
    kind, render_args = render_calls[-1]
    assert kind == "pdf"
    assert "## 1. Console Debian" in render_args["content"]
    assert "![Capture 2](C:/captures/two.png)" in render_args["content"]
    assert "apt update" in render_args["content"]
    invalid_format = await screenshots.generate_document(
        {"conversation_id": "conv-1", "format": "exe"}
    )
    assert "Format invalide" in invalid_format.get("error", "")
    missing_conversation = await screenshots.generate_document({})
    assert "conversation_id" in missing_conversation.get("error", "")

    with tempfile.TemporaryDirectory(prefix="marvin-screenshots-") as temp:
        image_path = Path(temp) / "capture.png"
        Image.new("RGB", (320, 200), "white").save(image_path)
        with (
            patch.object(
                screenshots.cloud_routing,
                "is_local_only_lockdown",
                return_value=False,
            ),
            patch.object(
                screenshots.cloud_routing,
                "get_cloud_config",
                return_value=(True, {}),
            ),
            patch.object(
                screenshots.cloud_routing,
                "get_privacy_preset",
                return_value="cloud_max",
            ),
            patch.object(
                screenshots.cloud_routing,
                "list_vision_candidates",
                return_value=["vision-cloud:cloud"],
            ),
            patch.object(
                screenshots.cloud_routing,
                "is_cloud_only_mode",
                return_value=False,
            ),
            patch.object(
                screenshots.cloud_routing,
                "record_model_capability",
            ) as record,
        ):
            analyzed = await screenshots.analyze(str(image_path))
        assert analyzed == {
            "caption": "Fenêtre de terminal Debian",
            "ocr_text": "apt update\nLecture des paquets",
            "model": "vision-cloud:cloud",
        }
        record.assert_called_once_with("vision-cloud:cloud", "vision", True)
        assert requests[-1]["options"]["temperature"] == 0.1

        with (
            patch.object(screenshots.cloud_routing, "is_local_only_lockdown", return_value=False),
            patch.object(screenshots.cloud_routing, "get_cloud_config", return_value=(True, {})),
            patch.object(screenshots.cloud_routing, "get_privacy_preset", return_value="normal"),
            patch.object(screenshots.cloud_routing, "is_cloud_only_mode", return_value=False),
        ):
            normal = await screenshots.analyze(str(image_path))
        assert normal["model"] == "qwen3.5:2b"

        with (
            patch.object(
                screenshots.cloud_routing,
                "is_local_only_lockdown",
                return_value=False,
            ),
            patch.object(
                screenshots.cloud_routing,
                "get_cloud_config",
                return_value=(True, {}),
            ),
            patch.object(
                screenshots.cloud_routing,
                "list_vision_candidates",
                return_value=[],
            ),
            patch.object(
                screenshots.cloud_routing,
                "is_cloud_only_mode",
                return_value=True,
            ),
        ):
            cloud_only = await screenshots.analyze(str(image_path))
        assert cloud_only.get("cloud_only") is True

    screenshots.configure(
        list_screenshots=db.list_screenshots,
        ollama_url=tools.OLLAMA_URL,
    )
    screenshots.configure_renderers(
        create_docx=tools.execute_file_create_docx,
        create_pdf=tools.execute_file_create_pdf,
    )
    assert tools._analyze_screenshot is screenshots.analyze
    assert tools.execute_screenshot_list is screenshots.list_for_conversation
    assert tools.execute_doc_generate_from_screenshots is screenshots.generate_document


if __name__ == "__main__":
    asyncio.run(_run())
    print("Screenshot document domain tests passed.")
