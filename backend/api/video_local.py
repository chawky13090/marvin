"""API de génération vidéo IA locale et amélioration de prompt Ollama."""

from __future__ import annotations

import json
import os
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import database as db
import api_errors
import local_video


router = APIRouter()


def video_generation_allowed() -> bool:
    """Applique le réglage de performance, ou la capacité GPU en son absence."""
    value = db.get_setting("video_gen_enabled")
    if value is None:
        try:
            return bool(local_video.get_device_info().get("video_gen_supported"))
        except Exception:
            return False
    return bool(value)


def video_generation_reason() -> str:
    try:
        info = local_video.get_device_info()
    except Exception:
        info = {}
    if not info.get("video_gen_supported"):
        return (
            "Génération vidéo locale indisponible sur ce matériel "
            f"({info.get('gpu') or info.get('vendor') or 'pas de GPU CUDA'}). "
            "Elle nécessite une carte NVIDIA/CUDA."
        )
    return (
        "Génération vidéo locale désactivée dans le mode de performance actuel. "
        "Passe en mode « Performance » ou « Maximum » (Mon jour → Auto-config) pour l'activer."
    )


@router.get("/api/video/local/models")
async def local_video_models():
    status = local_video.get_models_status()
    if isinstance(status, dict):
        status["video_gen_enabled"] = video_generation_allowed()
    return status


class LocalVideoTextRequest(BaseModel):
    model_key: str
    prompt: str
    num_steps: int | None = None
    num_frames: int | None = None
    fps: int | None = None
    guidance: float | None = None
    duration: float | None = None
    resolution: int | None = None
    seed: int | None = None
    negative_prompt: str | None = None


@router.post("/api/video/local/generate")
async def local_video_generate_text(body: LocalVideoTextRequest):
    async def generate():
        if not video_generation_allowed():
            yield f"data: {json.dumps({'status': 'error', 'error': video_generation_reason()})}\n\n"
            return
        async for event in local_video.generate_video_local_sse(
            model_key=body.model_key,
            prompt=body.prompt,
            num_steps=body.num_steps,
            num_frames=body.num_frames,
            fps=body.fps,
            guidance=body.guidance,
            duration=body.duration,
            resolution=body.resolution,
            seed=body.seed,
            negative_prompt=body.negative_prompt,
        ):
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


@router.post("/api/video/local/cancel")
async def local_video_cancel():
    local_video.request_cancel()
    return {"success": True, "message": "Annulation demandée — arrêt à la prochaine étape."}


class PromptEnhanceRequest(BaseModel):
    prompt: str


@router.post("/api/video/enhance-prompt")
async def enhance_video_prompt(body: PromptEnhanceRequest):
    raw_prompt = (body.prompt or "").strip()
    if not raw_prompt:
        raise HTTPException(status_code=400, detail="Prompt vide")

    system_prompt = (
        "You are a prompt engineer for an AI text-to-video model (Stable Diffusion 1.5 based). "
        "Rewrite the user's idea into ONE single rich English prompt, optimized for video generation. "
        "Rules: translate to English; keep the user's subject and intent EXACTLY; add concrete visual "
        "details (lighting, camera angle, environment, mood, colors, style like 'cinematic, 4k, detailed'); "
        "describe motion suitable for a short clip; NO preamble, NO quotes, NO explanations, NO line breaks. "
        "Output ONLY the final prompt, under 60 words."
    )
    try:
        import cloud_routing
        import tools

        generated = await tools._ollama_generate(
            f"{system_prompt}\n\nUSER IDEA:\n{raw_prompt}",
            timeout=60,
            return_metadata=True,
        )
        enhanced = str(generated.get("text") or "").strip()
        enhanced = enhanced.strip().strip('"').strip("'").replace("\n", " ").strip()
        if not enhanced:
            raise ValueError("réponse vide")
        model = str(generated.get("model") or "")
        return {
            "success": True,
            "original": raw_prompt,
            "enhanced": enhanced,
            "model": model,
            "provider": (
                "ollama_cloud"
                if cloud_routing.is_cloud_model(model)
                else "ollama_local"
            ),
            "privacy_preset": cloud_routing.get_privacy_preset(),
            "cloud_only": cloud_routing.is_cloud_only_mode(),
        }
    except Exception as exc:
        raise api_errors.internal_http_error(
            "video_prompt_enhance", exc, "Amélioration du prompt impossible."
        ) from exc


@router.post("/api/video/local/generate/image")
async def local_video_generate_image(
    model_key: str = Form(...),
    prompt: str = Form(""),
    num_steps: int | None = Form(None),
    image: UploadFile = File(...),
):
    extension = ".jpg"
    if image.content_type:
        if "png" in image.content_type:
            extension = ".png"
        elif "webp" in image.content_type:
            extension = ".webp"
    with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as temporary:
        temporary.write(await image.read())
        temporary_path = temporary.name

    async def generate():
        try:
            if not video_generation_allowed():
                yield f"data: {json.dumps({'status': 'error', 'error': video_generation_reason()})}\n\n"
                return
            async for event in local_video.generate_video_local_sse(
                model_key=model_key,
                prompt=prompt,
                num_steps=num_steps,
                image_path=temporary_path,
            ):
                yield event
        finally:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
