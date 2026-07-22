"""API vidéo distante : modèles Replicate, génération, suivi, annulation et import."""

from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import credentials_manager
import video_manager


router = APIRouter()


class VideoGenerateTextRequest(BaseModel):
    model_key: str
    prompt: str
    extra_params: dict = Field(default_factory=dict)


@router.get("/api/video/models")
async def video_models():
    return {
        "text_to_video": video_manager.TEXT_TO_VIDEO_MODELS,
        "image_to_video": video_manager.IMAGE_TO_VIDEO_MODELS,
    }


def _replicate_token(*, detailed: bool = False) -> str:
    token = credentials_manager.get_credential("replicate_api_token")
    if not token:
        detail = "Token Replicate non configuré"
        if detailed:
            detail += " (Paramètres > Connexions)"
        raise HTTPException(status_code=400, detail=detail)
    return token


@router.post("/api/video/generate/text")
async def video_generate_text(body: VideoGenerateTextRequest):
    model = video_manager.TEXT_TO_VIDEO_MODELS.get(body.model_key)
    if not model:
        raise HTTPException(status_code=404, detail=f"Modèle inconnu : {body.model_key}")
    if model["provider"] != "replicate":
        raise HTTPException(status_code=400, detail=f"Provider non supporté : {model['provider']}")
    token = _replicate_token(detailed=True)
    params = {**model["params"], "prompt": body.prompt, **body.extra_params}
    try:
        data = await video_manager._replicate_start(model["model_id"], params, token)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "success": True,
        "prediction_id": data["id"],
        "status": data.get("status", "starting"),
        "provider": "replicate",
        "model_name": model["name"],
    }


@router.post("/api/video/generate/image")
async def video_generate_image(
    model_key: str = Form(...),
    prompt: str = Form(""),
    image: UploadFile = File(...),
):
    model = video_manager.IMAGE_TO_VIDEO_MODELS.get(model_key)
    if not model:
        raise HTTPException(status_code=404, detail=f"Modèle inconnu : {model_key}")
    extension = ".jpg"
    if image.content_type:
        if "png" in image.content_type:
            extension = ".png"
        elif "webp" in image.content_type:
            extension = ".webp"
        elif "gif" in image.content_type:
            extension = ".gif"
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as temporary:
            temporary.write(await image.read())
            temporary_path = temporary.name
        image_uri = video_manager.image_to_data_uri(temporary_path)
        if model["provider"] != "replicate":
            raise HTTPException(status_code=400, detail=f"Provider non supporté : {model['provider']}")
        token = _replicate_token()
        params = dict(model["params"])
        for field in ("input_image", "image", "first_frame_image"):
            if field in params:
                params[field] = image_uri
                break
        if "prompt" in params:
            params["prompt"] = prompt
        data = await video_manager._replicate_start(model["model_id"], params, token)
        return {
            "success": True,
            "prediction_id": data["id"],
            "status": data.get("status", "starting"),
            "provider": "replicate",
            "model_name": model["name"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


@router.get("/api/video/status/{prediction_id}")
async def video_status_stream(prediction_id: str):
    token = _replicate_token()

    async def generate():
        async for event in video_manager.poll_replicate_sse(prediction_id, token):
            yield event

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/api/video/cancel/{prediction_id}")
async def video_cancel(prediction_id: str):
    await video_manager._replicate_cancel(prediction_id, _replicate_token())
    return {"success": True}


@router.post("/api/video/download")
async def video_download_url(request: Request):
    url = (await request.json()).get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL requise")
    try:
        path = await video_manager.download_video(url)
        filename = os.path.basename(path)
        size = os.path.getsize(path)
        return {
            "success": True,
            "filename": filename,
            "size": size,
            "size_human": video_manager._fmt_size(size),
            "url": f"/api/video/files/{filename}",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
