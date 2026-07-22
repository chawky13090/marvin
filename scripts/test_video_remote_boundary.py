"""Régressions de la frontière vidéo distante Replicate."""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from api import video_remote


async def _run() -> None:
    model = {
        "provider": "replicate",
        "model_id": "owner/model",
        "name": "Test Model",
        "params": {"duration": 5},
    }
    start = AsyncMock(return_value={"id": "prediction-1", "status": "starting"})
    with (
        patch.object(video_remote.video_manager, "TEXT_TO_VIDEO_MODELS", {"test": model}),
        patch.object(video_remote.credentials_manager, "get_credential", return_value="token"),
        patch.object(video_remote.video_manager, "_replicate_start", start),
    ):
        result = await video_remote.video_generate_text(
            video_remote.VideoGenerateTextRequest(
                model_key="test", prompt="Un réseau animé", extra_params={"duration": 8}
            )
        )
    assert result["prediction_id"] == "prediction-1"
    start.assert_awaited_once_with(
        "owner/model", {"duration": 8, "prompt": "Un réseau animé"}, "token"
    )

    image_model = {**model, "params": {"input_image": None, "prompt": ""}}
    upload = UploadFile(filename="image.png", file=io.BytesIO(b"PNG"))
    start = AsyncMock(return_value={"id": "prediction-2"})
    with (
        patch.object(video_remote.video_manager, "IMAGE_TO_VIDEO_MODELS", {"image": image_model}),
        patch.object(video_remote.credentials_manager, "get_credential", return_value="token"),
        patch.object(video_remote.video_manager, "image_to_data_uri", return_value="data:image/png;base64,UE5H"),
        patch.object(video_remote.video_manager, "_replicate_start", start),
    ):
        result = await video_remote.video_generate_image("image", "Anime", upload)
    assert result["prediction_id"] == "prediction-2"
    parameters = start.call_args.args[1]
    assert parameters["input_image"].startswith("data:image/png")
    assert parameters["prompt"] == "Anime"

    with patch.object(video_remote.credentials_manager, "get_credential", return_value=None):
        try:
            await video_remote.video_cancel("prediction")
        except HTTPException as exc:
            assert exc.status_code == 400 and "Token Replicate" in exc.detail
        else:
            raise AssertionError("Une opération Replicate sans jeton doit être refusée")


def main() -> int:
    asyncio.run(_run())
    import main as application

    expected = {
        ("/api/video/models", "GET"),
        ("/api/video/generate/text", "POST"),
        ("/api/video/generate/image", "POST"),
        ("/api/video/status/{prediction_id}", "GET"),
        ("/api/video/cancel/{prediction_id}", "POST"),
        ("/api/video/download", "POST"),
    }
    observed: set[tuple[str, str]] = set()
    for route in application.app.routes:
        endpoint = getattr(route, "endpoint", None)
        for method in getattr(route, "methods", set()):
            pair = (getattr(route, "path", ""), method)
            if pair in expected:
                assert endpoint.__module__ == "api.video_remote", pair
                observed.add(pair)
    assert observed == expected, sorted(expected - observed)
    print("Video Remote Boundary OK - modèles, texte, image, token, SSE et 6 routes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
