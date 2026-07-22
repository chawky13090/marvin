"""Régressions de la frontière de génération vidéo IA locale."""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from api import video_local


async def _body(response) -> str:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


async def _run() -> None:
    with (
        patch.object(video_local.db, "get_setting", return_value=None),
        patch.object(
            video_local.local_video,
            "get_device_info",
            return_value={"video_gen_supported": True},
        ),
    ):
        assert video_local.video_generation_allowed() is True

    with patch.object(video_local.db, "get_setting", return_value=False):
        assert video_local.video_generation_allowed() is False

    with (
        patch.object(video_local, "video_generation_allowed", return_value=False),
        patch.object(video_local, "video_generation_reason", return_value="GPU indisponible"),
        patch.object(video_local.local_video, "generate_video_local_sse") as generate,
    ):
        response = await video_local.local_video_generate_text(
            video_local.LocalVideoTextRequest(model_key="test", prompt="réseau")
        )
        content = await _body(response)
    assert "GPU indisponible" in content
    generate.assert_not_called()

    upload = UploadFile(filename="source.png", file=io.BytesIO(b"PNG"))
    deleted: list[str] = []

    def remove(path: str) -> None:
        deleted.append(path)
        os.remove(path)

    with (
        patch.object(video_local, "video_generation_allowed", return_value=False),
        patch.object(video_local, "video_generation_reason", return_value="désactivée"),
        patch.object(video_local.os, "unlink", side_effect=remove),
    ):
        response = await video_local.local_video_generate_image(
            model_key="test", prompt="", num_steps=None, image=upload
        )
        content = await _body(response)
    assert json.loads(content.removeprefix("data: ").strip())["error"] == "désactivée"
    assert deleted and all(not Path(path).exists() for path in deleted)

    with patch.object(video_local.local_video, "request_cancel") as cancel:
        result = await video_local.local_video_cancel()
    assert result["success"] is True
    cancel.assert_called_once_with()

    try:
        await video_local.enhance_video_prompt(video_local.PromptEnhanceRequest(prompt="  "))
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("Un prompt vide doit être refusé")


def main() -> int:
    asyncio.run(_run())
    import main as application

    expected = {
        ("/api/video/local/models", "GET"),
        ("/api/video/local/generate", "POST"),
        ("/api/video/local/cancel", "POST"),
        ("/api/video/enhance-prompt", "POST"),
        ("/api/video/local/generate/image", "POST"),
    }
    observed: set[tuple[str, str]] = set()
    for route in application.app.routes:
        endpoint = getattr(route, "endpoint", None)
        for method in getattr(route, "methods", set()):
            pair = (getattr(route, "path", ""), method)
            if pair in expected:
                assert endpoint.__module__ == "api.video_local", pair
                observed.add(pair)
    assert observed == expected, sorted(expected - observed)
    print("Video Local Boundary OK - capacité, SSE, nettoyage, annulation et 5 routes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
