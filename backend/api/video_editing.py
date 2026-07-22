"""API vidéo locale déterministe : création, fichiers et montage ffmpeg."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import video_manager


router = APIRouter()


def _uploaded_extension(upload: UploadFile, default: str = ".jpg") -> str:
    content_type = upload.content_type or ""
    for name in ("png", "webp", "gif"):
        if name in content_type:
            return f".{name}"
    return default


def _video_path(filename: str) -> Path:
    """Résout un nom simple sans autoriser une sortie du stockage vidéo."""
    if not filename or filename != Path(filename).name:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    directory = video_manager.get_video_dir().resolve()
    path = (directory / filename).resolve()
    if path.parent != directory:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    return path


@router.post("/api/video/slideshow")
async def video_slideshow(
    images: list[UploadFile] = File(...),
    format: str = Form("gif"),
    duration: float = Form(2.0),
    transition_frames: int = Form(8),
    fps: int = Form(24),
    fade_duration: float = Form(0.5),
    width: int = Form(640),
    height: int = Form(480),
):
    if not images:
        raise HTTPException(status_code=400, detail="Au moins une image requise")

    temporary_paths: list[str] = []
    try:
        for image in images:
            with tempfile.NamedTemporaryFile(
                suffix=_uploaded_extension(image), delete=False
            ) as temporary:
                temporary.write(await image.read())
                temporary_paths.append(temporary.name)

        resize_to = (width, height)
        loop = asyncio.get_running_loop()
        if format.lower() == "mp4":
            output_path = await loop.run_in_executor(
                None,
                lambda: video_manager.create_slideshow_mp4(
                    temporary_paths,
                    duration_per_image=duration,
                    fps=fps,
                    resize_to=resize_to,
                    fade_duration=fade_duration,
                ),
            )
        else:
            output_path = await loop.run_in_executor(
                None,
                lambda: video_manager.create_slideshow_gif(
                    temporary_paths,
                    duration_per_frame=duration,
                    resize_to=resize_to,
                    transition_frames=transition_frames,
                ),
            )

        filename = os.path.basename(output_path)
        size = os.path.getsize(output_path)
        return {
            "success": True,
            "filename": filename,
            "size": size,
            "size_human": video_manager._fmt_size(size),
            "format": format.upper(),
            "url": f"/api/video/files/{filename}",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        for path in temporary_paths:
            try:
                os.unlink(path)
            except OSError:
                pass


class VideoTextAnimRequest(BaseModel):
    text: str
    style: str = "typewriter"
    duration: float = 5.0
    fps: int = 24
    width: int = 854
    height: int = 480
    output_format: str = "mp4"
    font_size: int = 40


@router.post("/api/video/text-animation")
async def video_text_animation(body: VideoTextAnimRequest):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Texte requis")
    try:
        output_path = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: video_manager.create_text_animation_video(
                text=body.text,
                style=body.style,
                fps=body.fps,
                duration=body.duration,
                width=body.width,
                height=body.height,
                font_size=body.font_size,
                output_format=body.output_format,
            ),
        )
        filename = os.path.basename(output_path)
        size = os.path.getsize(output_path)
        return {
            "success": True,
            "filename": filename,
            "size": size,
            "size_human": video_manager._fmt_size(size),
            "format": os.path.splitext(filename)[1].lstrip(".").upper(),
            "url": f"/api/video/files/{filename}",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/video/files")
async def list_video_files():
    files = video_manager.list_generated_videos()
    return {"files": files, "count": len(files)}


@router.get("/api/video/files/{filename}")
async def serve_video_file(filename: str):
    path = _video_path(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    media_types = {
        ".mp4": "video/mp4",
        ".gif": "image/gif",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
    }
    return FileResponse(
        str(path),
        media_type=media_types.get(path.suffix.lower(), "application/octet-stream"),
        filename=filename,
    )


@router.delete("/api/video/files/{filename}")
async def delete_video_file(filename: str):
    path = _video_path(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    path.unlink()
    return {"success": True}


def _video_edit_result(result: dict) -> dict:
    if not result or result.get("error"):
        raise HTTPException(
            status_code=500,
            detail=(result or {}).get("error", "Échec du traitement"),
        )
    output = dict(result)
    path = result.get("path")
    if path:
        filename = os.path.basename(path)
        output["filename"] = filename
        output["url"] = f"/api/video/files/{filename}"
    return output


@router.post("/api/video/edit")
async def video_edit(
    operation: str = Form(...),
    file: UploadFile = File(None),
    fps: float = Form(None),
    width: int = Form(None),
    height: int = Form(None),
    start: float = Form(None),
    end: float = Form(None),
    duration: float = Form(None),
    crf: int = Form(None),
    scale_width: int = Form(None),
    factor: float = Form(None),
    colors: int = Form(None),
    text: str = Form(None),
    position: str = Form("bottom-right"),
    font_size: int = Form(24),
    region: str = Form(None),
    max_frames: int = Form(30),
):
    operation_name = (operation or "").strip().lower()
    temporary_path: str | None = None
    loop = asyncio.get_running_loop()

    try:
        if operation_name != "screen_record":
            if file is None:
                raise HTTPException(status_code=400, detail="Fichier requis pour cette opération")
            suffix = os.path.splitext(file.filename or "")[1] or ".mp4"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
                temporary.write(await file.read())
                temporary_path = temporary.name

        if operation_name == "info":
            result = await loop.run_in_executor(
                None, lambda: video_manager.get_media_info(temporary_path)
            )
            if result.get("error"):
                raise HTTPException(status_code=500, detail=result["error"])
            return {"success": True, **result}
        if operation_name == "to_gif":
            result = await loop.run_in_executor(
                None,
                lambda: video_manager.video_to_gif(
                    temporary_path,
                    fps=int(fps) if fps else 12,
                    width=width or 480,
                    start=start,
                    duration=duration,
                ),
            )
        elif operation_name == "gif_to_video":
            result = await loop.run_in_executor(
                None,
                lambda: video_manager.gif_to_video(
                    temporary_path, fps=int(fps) if fps else None
                ),
            )
        elif operation_name == "trim":
            result = await loop.run_in_executor(
                None,
                lambda: video_manager.video_trim(
                    temporary_path, start=start or 0, end=end, duration=duration
                ),
            )
        elif operation_name == "compress":
            result = await loop.run_in_executor(
                None,
                lambda: video_manager.video_compress(
                    temporary_path, crf=crf or 28, scale_width=scale_width
                ),
            )
        elif operation_name == "resize":
            result = await loop.run_in_executor(
                None,
                lambda: video_manager.video_resize(
                    temporary_path, width=width, height=height
                ),
            )
        elif operation_name == "extract_frames":
            result = await loop.run_in_executor(
                None,
                lambda: video_manager.video_extract_frames(
                    temporary_path, fps=fps or 1, max_frames=max_frames or 30
                ),
            )
            if result.get("error"):
                raise HTTPException(status_code=500, detail=result["error"])
            return {"success": True, **result}
        elif operation_name == "speed":
            result = await loop.run_in_executor(
                None,
                lambda: video_manager.video_speed(temporary_path, factor=factor or 2.0),
            )
        elif operation_name == "watermark":
            if not text:
                raise HTTPException(
                    status_code=400, detail="Paramètre 'text' requis pour le filigrane"
                )
            result = await loop.run_in_executor(
                None,
                lambda: video_manager.video_add_watermark(
                    temporary_path,
                    text,
                    position=position or "bottom-right",
                    font_size=font_size or 24,
                ),
            )
        elif operation_name == "optimize_gif":
            result = await loop.run_in_executor(
                None,
                lambda: video_manager.gif_optimize(
                    temporary_path,
                    fps=int(fps) if fps else 10,
                    width=width,
                    colors=colors or 128,
                ),
            )
        elif operation_name == "screen_record":
            parsed_region = None
            if region:
                try:
                    parsed_region = [int(value) for value in region.split(",")]
                except ValueError:
                    parsed_region = None
            result = await loop.run_in_executor(
                None,
                lambda: video_manager.screen_record_gif(
                    duration=min(duration or 5, 20),
                    fps=int(fps) if fps else 10,
                    region=parsed_region,
                ),
            )
        else:
            raise HTTPException(status_code=400, detail=f"Opération inconnue : {operation}")

        return _video_edit_result(result)
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
