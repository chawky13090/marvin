"""Régressions de la frontière création, fichiers et montage vidéo local."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from api import video_editing


async def _run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        output = root / "animation.mp4"
        output.write_bytes(b"video")
        with (
            patch.object(video_editing.video_manager, "create_text_animation_video", return_value=str(output)) as create,
            patch.object(video_editing.video_manager, "_fmt_size", return_value="5 o"),
        ):
            result = await video_editing.video_text_animation(
                video_editing.VideoTextAnimRequest(text="Marvin", style="fade")
            )
        assert result["filename"] == "animation.mp4"
        assert result["url"] == "/api/video/files/animation.mp4"
        assert create.call_args.kwargs["style"] == "fade"

        with patch.object(video_editing.video_manager, "get_video_dir", return_value=root):
            assert video_editing._video_path("animation.mp4") == output.resolve()
            try:
                video_editing._video_path("../secret.txt")
            except HTTPException as exc:
                assert exc.status_code == 400
            else:
                raise AssertionError("Une traversée de répertoire doit être refusée")

    with patch.object(
        video_editing.video_manager,
        "screen_record_gif",
        return_value={"path": "C:/video/capture.gif", "size": 10},
    ) as record:
        result = await video_editing.video_edit(
            operation="screen_record",
            file=None,
            fps=12,
            width=None,
            height=None,
            start=None,
            end=None,
            duration=99,
            crf=None,
            scale_width=None,
            factor=None,
            colors=None,
            text=None,
            position="bottom-right",
            font_size=24,
            region="1,2,300,200",
            max_frames=30,
        )
    assert result["filename"] == "capture.gif"
    assert record.call_args.kwargs == {
        "duration": 20,
        "fps": 12,
        "region": [1, 2, 300, 200],
    }


def main() -> int:
    asyncio.run(_run())
    import main as application

    expected = {
        ("/api/video/slideshow", "POST"),
        ("/api/video/text-animation", "POST"),
        ("/api/video/files", "GET"),
        ("/api/video/files/{filename}", "GET"),
        ("/api/video/files/{filename}", "DELETE"),
        ("/api/video/edit", "POST"),
    }
    observed: set[tuple[str, str]] = set()
    for route in application.app.routes:
        endpoint = getattr(route, "endpoint", None)
        for method in getattr(route, "methods", set()):
            pair = (getattr(route, "path", ""), method)
            if pair in expected:
                assert endpoint.__module__ == "api.video_editing", pair
                observed.add(pair)
    assert observed == expected, sorted(expected - observed)
    print("Video Editing Boundary OK - création, fichiers sûrs, ffmpeg et 6 routes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
