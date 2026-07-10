"""
video_manager.py — Génération vidéo IA (Replicate / fal.ai) + slideshow local.
"""
import os
import uuid
import asyncio
import base64
import json
import tempfile
from pathlib import Path
from typing import Optional
import httpx

# ── Répertoire de sortie vidéo ───────────────────────────────────────────────

_VIDEO_DIR = Path(__file__).parent / "generated_videos"
_VIDEO_DIR.mkdir(exist_ok=True)


def get_video_dir() -> Path:
    return _VIDEO_DIR


# ── Modèles disponibles ──────────────────────────────────────────────────────

TEXT_TO_VIDEO_MODELS = {
    "wan-480p": {
        "name": "Wan 2.1 T2V 480p",
        "provider": "replicate",
        "model_id": "wavespeed-ai/wan-2.1-t2v-480p",
        "description": "Vidéo HD 480p, ~5s, rapide",
        "params": {
            "prompt": "",
            "num_frames": 81,
            "frames_per_second": 16,
            "guidance_scale": 5,
            "num_inference_steps": 30,
        },
    },
    "wan-720p": {
        "name": "Wan 2.1 T2V 720p",
        "provider": "replicate",
        "model_id": "wavespeed-ai/wan-2.1-t2v-720p",
        "description": "Vidéo HD 720p, haute qualité",
        "params": {
            "prompt": "",
            "num_frames": 81,
            "frames_per_second": 16,
            "guidance_scale": 5,
            "num_inference_steps": 30,
        },
    },
    "minimax": {
        "name": "MiniMax Video-01",
        "provider": "replicate",
        "model_id": "minimax/video-01",
        "description": "Qualité cinématographique, 6s",
        "params": {
            "prompt": "",
            "prompt_optimizer": True,
        },
    },
    "animatediff": {
        "name": "AnimateDiff Lightning",
        "provider": "replicate",
        "model_id": "lucataco/animatediff-lightning-4step",
        "description": "Animation rapide, style artistique",
        "params": {
            "prompt": "",
            "num_frames": 16,
            "guidance_scale": 2.0,
        },
    },
    "luma": {
        "name": "Luma Dream Machine",
        "provider": "replicate",
        "model_id": "luma/dream-machine",
        "description": "Haute cohérence physique",
        "params": {
            "prompt": "",
            "loop": False,
        },
    },
}

IMAGE_TO_VIDEO_MODELS = {
    "svd": {
        "name": "Stable Video Diffusion XT",
        "provider": "replicate",
        "model_id": "stability-ai/stable-video-diffusion",
        "description": "Animation réaliste depuis une image",
        "params": {
            "input_image": None,
            "video_length": "25_frames_with_svd_xt",
            "sizing_strategy": "maintain_aspect_ratio",
            "frames_per_second": 6,
            "motion_bucket_id": 127,
            "cond_aug": 0.02,
            "decoding_t": 14,
        },
    },
    "wan-i2v": {
        "name": "Wan 2.1 I2V 480p",
        "provider": "replicate",
        "model_id": "wavespeed-ai/wan-2.1-i2v-480p",
        "description": "Anime une image en vidéo 480p",
        "params": {
            "image": None,
            "prompt": "",
            "num_frames": 81,
            "frames_per_second": 16,
        },
    },
    "minimax-i2v": {
        "name": "MiniMax Image-to-Video",
        "provider": "replicate",
        "model_id": "minimax/video-01-live",
        "description": "Vidéo de haute qualité depuis image",
        "params": {
            "first_frame_image": None,
            "prompt": "",
            "prompt_optimizer": True,
        },
    },
}


# ── Client Replicate ─────────────────────────────────────────────────────────

async def _replicate_start(model_id: str, input_params: dict, api_token: str) -> dict:
    """Lance une prédiction Replicate et retourne {id, status, urls}."""
    url = "https://api.replicate.com/v1/models/{}/predictions".format(model_id)
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Prefer": "wait",
    }
    payload = {"input": input_params}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _replicate_poll(prediction_id: str, api_token: str) -> dict:
    """Récupère l'état d'une prédiction Replicate."""
    url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
    headers = {"Authorization": f"Bearer {api_token}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _replicate_cancel(prediction_id: str, api_token: str):
    url = f"https://api.replicate.com/v1/predictions/{prediction_id}/cancel"
    headers = {"Authorization": f"Bearer {api_token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(url, headers=headers)


# ── fal.ai Client ────────────────────────────────────────────────────────────

async def _falai_start(model_id: str, input_params: dict, api_key: str) -> dict:
    """Lance une requête fal.ai (queue)."""
    url = f"https://queue.fal.run/{model_id}"
    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=input_params, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _falai_status(request_id: str, model_id: str, api_key: str) -> dict:
    url = f"https://queue.fal.run/{model_id}/requests/{request_id}/status"
    headers = {"Authorization": f"Key {api_key}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _falai_result(request_id: str, model_id: str, api_key: str) -> dict:
    url = f"https://queue.fal.run/{model_id}/requests/{request_id}"
    headers = {"Authorization": f"Key {api_key}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


# ── Polling SSE generator ─────────────────────────────────────────────────────

async def poll_replicate_sse(prediction_id: str, api_token: str):
    """
    Générateur asynchrone qui yield des événements SSE jusqu'à la fin.
    Yield: JSON string avec {status, progress, output_url, error, logs}
    """
    poll_interval = 2.0
    while True:
        try:
            data = await _replicate_poll(prediction_id, api_token)
            status = data.get("status", "unknown")
            logs   = data.get("logs", "") or ""
            output = data.get("output")
            error  = data.get("error")

            # Extraire URL de sortie
            output_url = None
            if output:
                if isinstance(output, str):
                    output_url = output
                elif isinstance(output, list) and output:
                    output_url = output[0]

            payload = {
                "status": status,
                "logs": logs[-500:] if logs else "",  # derniers 500 chars
                "output_url": output_url,
                "error": error,
                "prediction_id": prediction_id,
            }
            yield f"data: {json.dumps(payload)}\n\n"

            if status in ("succeeded", "failed", "canceled"):
                break

        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
            break

        await asyncio.sleep(poll_interval)


# ── Téléchargement vidéo générée ─────────────────────────────────────────────

async def download_video(url: str, filename: Optional[str] = None) -> str:
    """Télécharge une vidéo depuis une URL et la sauvegarde dans _VIDEO_DIR."""
    if not filename:
        ext = ".mp4"
        if ".gif" in url:
            ext = ".gif"
        elif ".webm" in url:
            ext = ".webm"
        filename = f"{uuid.uuid4()}{ext}"

    dest = _VIDEO_DIR / filename
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return str(dest)


# ── Slideshow local (sans API) ───────────────────────────────────────────────

def create_slideshow_gif(
    image_paths: list[str],
    duration_per_frame: float = 2.0,
    loop: int = 0,
    resize_to: tuple[int, int] = (640, 480),
    transition_frames: int = 8,
) -> str:
    """
    Crée un GIF animé (ou MP4) depuis une liste d'images locales avec transition en fondu.
    Retourne le chemin du fichier créé.
    """
    from PIL import Image as PILImage
    import io

    if not image_paths:
        raise ValueError("Aucune image fournie")

    frames = []
    frame_durations = []

    def load_and_resize(path: str) -> PILImage.Image:
        img = PILImage.open(path).convert("RGBA")
        img.thumbnail(resize_to, PILImage.LANCZOS)
        # Centrer sur fond noir
        background = PILImage.new("RGBA", resize_to, (0, 0, 0, 255))
        offset = ((resize_to[0] - img.width) // 2, (resize_to[1] - img.height) // 2)
        background.paste(img, offset, img if img.mode == "RGBA" else None)
        return background.convert("RGB")

    images = [load_and_resize(p) for p in image_paths]

    # Construction frames avec transition en fondu entre images
    for i, img in enumerate(images):
        # Frames de l'image courante
        hold_ms = int(duration_per_frame * 1000)
        frames.append(img)
        frame_durations.append(hold_ms)

        # Transition fondu vers l'image suivante
        if i < len(images) - 1 and transition_frames > 0:
            next_img = images[i + 1]
            for t in range(1, transition_frames + 1):
                alpha = t / (transition_frames + 1)
                blended = PILImage.blend(img, next_img, alpha)
                frames.append(blended)
                frame_durations.append(max(40, int(300 / transition_frames)))

    # Sauvegarder en GIF animé
    out_path = _VIDEO_DIR / f"slideshow_{uuid.uuid4()}.gif"
    frames[0].save(
        str(out_path),
        save_all=True,
        append_images=frames[1:],
        duration=frame_durations,
        loop=loop,
        optimize=False,
    )
    return str(out_path)


def create_slideshow_mp4(
    image_paths: list[str],
    duration_per_image: float = 3.0,
    fps: int = 24,
    resize_to: tuple[int, int] = (854, 480),
    fade_duration: float = 0.5,
) -> str:
    """
    Crée un MP4 depuis des images avec transitions en fondu (via moviepy).
    Retourne le chemin du fichier créé.
    """
    try:
        from moviepy import ImageClip, concatenate_videoclips, vfx
    except ImportError:
        from moviepy.editor import ImageClip, concatenate_videoclips
        from moviepy import vfx

    clips = []
    for path in image_paths:
        clip = (
            ImageClip(path)
            .resized(resize_to)
            .with_duration(duration_per_image)
        )
        if fade_duration > 0:
            try:
                clip = clip.with_effects([vfx.CrossFadeIn(fade_duration), vfx.CrossFadeOut(fade_duration)])
            except Exception:
                clip = clip.fadein(fade_duration).fadeout(fade_duration)
        clips.append(clip)

    if not clips:
        raise ValueError("Aucune image valide")

    video = concatenate_videoclips(clips, method="compose")
    out_path = _VIDEO_DIR / f"slideshow_{uuid.uuid4()}.mp4"
    video.write_videofile(str(out_path), fps=fps, codec="libx264", audio=False, logger=None)
    video.close()
    return str(out_path)


# ── Encode image en base64 data URI (pour les APIs) ──────────────────────────

def image_to_data_uri(path: str) -> str:
    """Convertit un fichier image en data URI base64."""
    ext = Path(path).suffix.lower().lstrip(".")
    mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "webp": "image/webp"}
    mime = mime_map.get(ext, "image/png")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def list_generated_videos() -> list[dict]:
    """Liste les vidéos/GIFs générés localement."""
    results = []
    for f in sorted(_VIDEO_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix.lower() in (".mp4", ".gif", ".webm", ".mov"):
            stat = f.stat()
            results.append({
                "filename": f.name,
                "size": stat.st_size,
                "size_human": _fmt_size(stat.st_size),
                "created_at": stat.st_mtime,
                "type": f.suffix.lstrip(".").upper(),
            })
    return results


def _fmt_size(b: int) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} To"


# ── Génération vidéo texte-animé (100% locale, sans GPU ni API) ──────────────

def create_text_animation_video(
    text: str,
    style: str = "typewriter",       # typewriter | fade | scroll | title
    fps: int = 24,
    duration: float = 5.0,
    width: int = 854,
    height: int = 480,
    bg_color: tuple = (10, 10, 20),
    text_color: tuple = (255, 255, 255),
    accent_color: tuple = (201, 168, 76),
    font_size: int = 40,
    output_format: str = "mp4",      # mp4 | gif
) -> str:
    """
    Crée une vidéo animée à partir de texte, sans GPU ni clé API.
    Styles : typewriter (frappe), fade (apparition), scroll (défilement), title (titre avec glow).
    """
    from PIL import Image as PILImage, ImageDraw, ImageFont
    import math, textwrap

    total_frames = int(fps * duration)
    frames = []

    # Try to use a decent font, fall back to default
    def _get_font(size):
        for font_path in [
            "C:/Windows/Fonts/Arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "C:/Windows/Fonts/verdana.ttf",
        ]:
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    font       = _get_font(font_size)
    font_small = _get_font(max(16, font_size // 2))

    # Wrap text
    wrapped = textwrap.fill(text, width=max(20, width // (font_size // 2)))
    lines   = wrapped.splitlines()

    def make_base_frame():
        img = PILImage.new("RGB", (width, height), bg_color)
        # Subtle gradient overlay
        draw = ImageDraw.Draw(img)
        for y in range(height):
            alpha = int(20 * (y / height))
            draw.line([(0, y), (width, y)],
                      fill=(bg_color[0] + alpha // 4, bg_color[1] + alpha // 4, bg_color[2] + alpha // 3))
        return img

    def draw_lines_on(img, visible_chars=None):
        draw = ImageDraw.Draw(img)
        total_h = len(lines) * (font_size + 8)
        y_start = (height - total_h) // 2
        drawn = 0
        for li, line in enumerate(lines):
            x = 40
            y = y_start + li * (font_size + 8)
            if visible_chars is not None:
                to_show = ""
                remaining = visible_chars - drawn
                if remaining <= 0:
                    break
                to_show = line[:remaining]
                drawn += len(to_show)
                # Shadow
                draw.text((x + 2, y + 2), to_show, font=font, fill=(0, 0, 0, 128))
                draw.text((x, y), to_show, font=font, fill=text_color)
            else:
                draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 128))
                draw.text((x, y), line, font=font, fill=text_color)
        # Accent line at bottom
        draw.rectangle([(0, height - 4), (width, height)],
                        fill=accent_color)
        return img

    if style == "typewriter":
        total_chars = sum(len(l) for l in lines)
        for f_idx in range(total_frames):
            img = make_base_frame()
            # First 80% of time: type chars; last 20%: hold
            progress = min(f_idx / (total_frames * 0.8), 1.0)
            visible = int(progress * total_chars)
            draw_lines_on(img, visible_chars=visible)
            frames.append(img)

    elif style == "fade":
        for f_idx in range(total_frames):
            img = make_base_frame()
            draw_lines_on(img)
            # Fade in first 30%, hold, fade out last 20%
            t = f_idx / total_frames
            if t < 0.3:
                alpha = t / 0.3
            elif t > 0.8:
                alpha = (1.0 - t) / 0.2
            else:
                alpha = 1.0
            alpha = max(0.0, min(1.0, alpha))
            black = PILImage.new("RGB", (width, height), bg_color)
            final = PILImage.blend(black, img, alpha)
            frames.append(final)

    elif style == "scroll":
        # Text scrolls up from bottom
        total_h  = len(lines) * (font_size + 8)
        scroll_h = height + total_h
        for f_idx in range(total_frames):
            img = make_base_frame()
            draw = ImageDraw.Draw(img)
            y_offset = int(height - (f_idx / total_frames) * scroll_h)
            for li, line in enumerate(lines):
                y = y_offset + li * (font_size + 8)
                if -font_size < y < height:
                    draw.text((42, y + 2), line, font=font, fill=(0, 0, 0))
                    draw.text((40, y), line, font=font, fill=text_color)
            draw.rectangle([(0, height - 4), (width, height)], fill=accent_color)
            frames.append(img)

    elif style == "title":
        for f_idx in range(total_frames):
            img = make_base_frame()
            draw = ImageDraw.Draw(img)
            t = f_idx / total_frames
            # Animated glow pulse
            glow_alpha = int(40 + 20 * math.sin(t * 2 * math.pi * 2))
            # Draw glow
            for offset in range(6, 0, -2):
                draw.text(
                    (width // 2 - len(lines[0]) * font_size // 4 + offset,
                     height // 2 - font_size // 2 + offset),
                    lines[0] if lines else text,
                    font=font, fill=(accent_color[0], accent_color[1], accent_color[2], glow_alpha),
                )
            # Title text
            if t < 0.2:
                scale = t / 0.2  # zoom in
            else:
                scale = 1.0
            y_pos = int(height // 2 - font_size * scale)
            draw.text((40, y_pos), "\n".join(lines), font=font, fill=accent_color)
            # Subtitle separator
            draw.rectangle([(40, height // 2 + font_size + 8),
                             (width - 40, height // 2 + font_size + 10)],
                            fill=accent_color)
            # Bottom credit
            draw.text((40, height - 40), "MARVIN AI", font=font_small, fill=accent_color)
            frames.append(img)
    else:
        # Default: static display
        img = make_base_frame()
        draw_lines_on(img)
        frames = [img] * total_frames

    # Write output
    out_name = f"text_anim_{uuid.uuid4()}"
    if output_format == "gif":
        out_path = _VIDEO_DIR / f"{out_name}.gif"
        frame_dur = max(20, int(1000 / fps))
        frames[0].save(
            str(out_path),
            save_all=True, append_images=frames[1:],
            duration=frame_dur, loop=0, optimize=True,
        )
    else:
        # MP4 via moviepy
        try:
            from moviepy import ImageClip, concatenate_videoclips
            frame_dur_s = 1.0 / fps
            clips = [ImageClip(frame_arr).with_duration(frame_dur_s)
                     for frame_arr in [
                         __import__('numpy').array(f) for f in frames
                     ]]
            video = concatenate_videoclips(clips, method="chain")
            out_path = _VIDEO_DIR / f"{out_name}.mp4"
            video.write_videofile(str(out_path), fps=fps, codec="libx264", audio=False, logger=None)
            video.close()
        except Exception:
            # Fallback to GIF if MP4 fails
            out_path = _VIDEO_DIR / f"{out_name}.gif"
            frame_dur = max(20, int(1000 / fps))
            frames[0].save(
                str(out_path),
                save_all=True, append_images=frames[1:],
                duration=frame_dur, loop=0,
            )
    return str(out_path)


# ══════════════════════════════════════════════════════════════════════════════
# v2.32 — Édition vidéo / GIF locale (ffmpeg) — sans GPU, sans API
# ══════════════════════════════════════════════════════════════════════════════

def _ffmpeg_exe() -> str:
    """Retourne le chemin du binaire ffmpeg embarqué."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"  # fallback PATH


def _ffprobe_exe() -> Optional[str]:
    """ffprobe si disponible (sinon None — on utilisera ffmpeg/moviepy)."""
    import shutil
    p = shutil.which("ffprobe")
    return p


def _run_ffmpeg(args: list, timeout: int = 300) -> tuple[int, str]:
    """Exécute ffmpeg avec les arguments donnés. Retourne (returncode, stderr)."""
    import subprocess
    cmd = [_ffmpeg_exe(), "-y", *args]
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", creationflags=flags)
    return proc.returncode, (proc.stderr or "")[-1500:]


def get_media_info(path: str) -> dict:
    """Métadonnées d'un fichier vidéo/GIF : durée, résolution, fps, codec, taille."""
    p = Path(path)
    if not p.exists():
        return {"error": f"Fichier introuvable : {path}"}
    info = {
        "filename": p.name,
        "size_bytes": p.stat().st_size,
        "size_human": _fmt_size(p.stat().st_size),
        "format": p.suffix.lstrip(".").upper(),
    }
    # Try moviepy (uses ffmpeg under the hood) for duration/fps/resolution
    try:
        try:
            from moviepy import VideoFileClip
        except ImportError:
            from moviepy.editor import VideoFileClip
        with VideoFileClip(str(p)) as clip:
            info["duration_sec"] = round(clip.duration, 2)
            info["width"] = clip.w
            info["height"] = clip.h
            info["fps"] = round(clip.fps, 2) if clip.fps else None
            info["resolution"] = f"{clip.w}x{clip.h}"
            info["has_audio"] = clip.audio is not None
            if clip.duration and clip.duration > 0:
                info["bitrate_kbps"] = round((p.stat().st_size * 8) / clip.duration / 1000, 1)
    except Exception as e:
        # GIF or unreadable by moviepy → try PIL for GIFs
        if p.suffix.lower() == ".gif":
            try:
                from PIL import Image as _Img
                with _Img.open(str(p)) as im:
                    info["width"], info["height"] = im.size
                    info["resolution"] = f"{im.width}x{im.height}"
                    n_frames = getattr(im, "n_frames", 1)
                    info["frames"] = n_frames
                    # Estimate duration from frame durations
                    try:
                        durations = []
                        for i in range(n_frames):
                            im.seek(i)
                            durations.append(im.info.get("duration", 100))
                        info["duration_sec"] = round(sum(durations) / 1000, 2)
                        info["fps"] = round(n_frames / (sum(durations) / 1000), 1) if sum(durations) else None
                    except Exception:
                        pass
            except Exception as e2:
                info["info_error"] = str(e2)
        else:
            info["info_error"] = str(e)
    return info


def video_to_gif(video_path: str, fps: int = 12, width: int = 480,
                 start: float = None, duration: float = None,
                 output_path: str = None) -> dict:
    """
    Convertit une vidéo en GIF optimisé (palette ffmpeg pour qualité/taille).
    width=480 par défaut (ratio préservé). start/duration pour découper.
    """
    src = Path(video_path)
    if not src.exists():
        return {"error": f"Fichier introuvable : {video_path}"}
    out = Path(output_path) if output_path else (_VIDEO_DIR / f"{src.stem}_{uuid.uuid4().hex[:8]}.gif")
    out.parent.mkdir(parents=True, exist_ok=True)

    # Palette-based 2-pass for high quality / small size
    vf = f"fps={fps},scale={width}:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
    pre = []
    if start is not None:
        pre += ["-ss", str(start)]
    if duration is not None:
        pre += ["-t", str(duration)]
    args = [*pre, "-i", str(src), "-vf", vf, "-loop", "0", str(out)]
    rc, err = _run_ffmpeg(args, timeout=300)
    if rc != 0 or not out.exists():
        return {"error": f"Conversion GIF échouée : {err[-300:]}"}
    return {"success": True, "path": str(out), "size_human": _fmt_size(out.stat().st_size),
            "size_bytes": out.stat().st_size}


def gif_to_video(gif_path: str, output_path: str = None, fps: int = None) -> dict:
    """Convertit un GIF en MP4 (bien plus léger qu'un GIF pour le partage)."""
    src = Path(gif_path)
    if not src.exists():
        return {"error": f"Fichier introuvable : {gif_path}"}
    out = Path(output_path) if output_path else (_VIDEO_DIR / f"{src.stem}_{uuid.uuid4().hex[:8]}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    # pad to even dimensions (libx264 requirement)
    vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    args = ["-i", str(src), "-movflags", "faststart", "-pix_fmt", "yuv420p", "-vf", vf]
    if fps:
        args += ["-r", str(fps)]
    args += [str(out)]
    rc, err = _run_ffmpeg(args)
    if rc != 0 or not out.exists():
        return {"error": f"Conversion MP4 échouée : {err[-300:]}"}
    return {"success": True, "path": str(out), "size_human": _fmt_size(out.stat().st_size),
            "size_bytes": out.stat().st_size}


def video_trim(video_path: str, start: float = 0, end: float = None,
               duration: float = None, output_path: str = None) -> dict:
    """Découpe un segment d'une vidéo (sans réencodage si possible → ultra rapide)."""
    src = Path(video_path)
    if not src.exists():
        return {"error": f"Fichier introuvable : {video_path}"}
    out = Path(output_path) if output_path else (_VIDEO_DIR / f"{src.stem}_trim_{uuid.uuid4().hex[:8]}{src.suffix}")
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["-ss", str(start), "-i", str(src)]
    if duration is not None:
        args += ["-t", str(duration)]
    elif end is not None:
        args += ["-to", str(max(0, end - start))]
    # Copy streams = no re-encode (fast). If it fails, caller can re-encode.
    args += ["-c", "copy", str(out)]
    rc, err = _run_ffmpeg(args)
    if rc != 0 or not out.exists() or out.stat().st_size < 1000:
        # Fallback with re-encode
        args2 = ["-ss", str(start), "-i", str(src)]
        if duration is not None:
            args2 += ["-t", str(duration)]
        elif end is not None:
            args2 += ["-to", str(max(0, end - start))]
        args2 += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]
        rc, err = _run_ffmpeg(args2)
        if rc != 0 or not out.exists():
            return {"error": f"Découpe échouée : {err[-300:]}"}
    return {"success": True, "path": str(out), "size_human": _fmt_size(out.stat().st_size),
            "size_bytes": out.stat().st_size}


def video_compress(video_path: str, crf: int = 28, scale_width: int = None,
                   output_path: str = None) -> dict:
    """Compresse une vidéo (CRF 18=haute qualité, 28=équilibré, 35=petit). Réduit la taille."""
    src = Path(video_path)
    if not src.exists():
        return {"error": f"Fichier introuvable : {video_path}"}
    out = Path(output_path) if output_path else (_VIDEO_DIR / f"{src.stem}_compressed_{uuid.uuid4().hex[:8]}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["-i", str(src), "-vcodec", "libx264", "-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p"]
    if scale_width:
        args += ["-vf", f"scale={scale_width}:-2"]
    args += ["-c:a", "aac", "-b:a", "128k", str(out)]
    rc, err = _run_ffmpeg(args)
    if rc != 0 or not out.exists():
        return {"error": f"Compression échouée : {err[-300:]}"}
    orig = src.stat().st_size
    new = out.stat().st_size
    ratio = round((1 - new / orig) * 100, 1) if orig > 0 else 0
    return {"success": True, "path": str(out),
            "original_size": _fmt_size(orig), "new_size": _fmt_size(new),
            "reduction_pct": ratio, "size_bytes": new}


def video_resize(video_path: str, width: int = None, height: int = None,
                 output_path: str = None) -> dict:
    """Redimensionne une vidéo. width OU height (ratio préservé) ou les deux."""
    src = Path(video_path)
    if not src.exists():
        return {"error": f"Fichier introuvable : {video_path}"}
    out = Path(output_path) if output_path else (_VIDEO_DIR / f"{src.stem}_resized_{uuid.uuid4().hex[:8]}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    if width and height:
        scale = f"{width}:{height}"
    elif width:
        scale = f"{width}:-2"
    elif height:
        scale = f"-2:{height}"
    else:
        return {"error": "Spécifiez width et/ou height."}
    args = ["-i", str(src), "-vf", f"scale={scale}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", str(out)]
    rc, err = _run_ffmpeg(args)
    if rc != 0 or not out.exists():
        return {"error": f"Redimensionnement échoué : {err[-300:]}"}
    return {"success": True, "path": str(out), "size_human": _fmt_size(out.stat().st_size)}


def video_extract_frames(video_path: str, fps: float = 1, max_frames: int = 30,
                         output_dir: str = None) -> dict:
    """Extrait des images d'une vidéo (fps=1 → 1 image/sec)."""
    src = Path(video_path)
    if not src.exists():
        return {"error": f"Fichier introuvable : {video_path}"}
    out_dir = Path(output_dir) if output_dir else (_VIDEO_DIR / f"frames_{src.stem}_{uuid.uuid4().hex[:8]}")
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "frame_%04d.png")
    args = ["-i", str(src), "-vf", f"fps={fps}", "-frames:v", str(max_frames), pattern]
    rc, err = _run_ffmpeg(args)
    frames = sorted(out_dir.glob("frame_*.png"))
    if not frames:
        return {"error": f"Extraction échouée : {err[-300:]}"}
    return {"success": True, "output_dir": str(out_dir), "frame_count": len(frames),
            "frames": [str(f) for f in frames[:max_frames]]}


def video_speed(video_path: str, factor: float = 2.0, output_path: str = None) -> dict:
    """Change la vitesse d'une vidéo (2.0=2x plus rapide, 0.5=ralenti)."""
    src = Path(video_path)
    if not src.exists():
        return {"error": f"Fichier introuvable : {video_path}"}
    if factor <= 0:
        return {"error": "factor doit être > 0"}
    out = Path(output_path) if output_path else (_VIDEO_DIR / f"{src.stem}_speed{factor}x_{uuid.uuid4().hex[:8]}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    # setpts = 1/factor for video ; atempo for audio (0.5-2.0 range, chain if needed)
    pts = round(1.0 / factor, 4)
    args = ["-i", str(src), "-filter:v", f"setpts={pts}*PTS",
            "-an",  # drop audio (atempo chaining is complex; keep it simple/robust)
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]
    rc, err = _run_ffmpeg(args)
    if rc != 0 or not out.exists():
        return {"error": f"Changement de vitesse échoué : {err[-300:]}"}
    return {"success": True, "path": str(out), "factor": factor,
            "size_human": _fmt_size(out.stat().st_size)}


def video_add_watermark(video_path: str, text: str, position: str = "bottom-right",
                        font_size: int = 24, output_path: str = None) -> dict:
    """Ajoute un texte/filigrane sur une vidéo."""
    src = Path(video_path)
    if not src.exists():
        return {"error": f"Fichier introuvable : {video_path}"}
    out = Path(output_path) if output_path else (_VIDEO_DIR / f"{src.stem}_wm_{uuid.uuid4().hex[:8]}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    pos_map = {
        "top-left": "x=15:y=15",
        "top-right": "x=w-tw-15:y=15",
        "bottom-left": "x=15:y=h-th-15",
        "bottom-right": "x=w-tw-15:y=h-th-15",
        "center": "x=(w-tw)/2:y=(h-th)/2",
    }
    pos = pos_map.get(position, pos_map["bottom-right"])
    # Escape special chars for ffmpeg drawtext
    safe_text = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’")
    draw = (f"drawtext=text='{safe_text}':fontcolor=white:fontsize={font_size}:"
            f"box=1:boxcolor=black@0.5:boxborderw=6:{pos}")
    args = ["-i", str(src), "-vf", draw, "-c:a", "copy", "-pix_fmt", "yuv420p", str(out)]
    rc, err = _run_ffmpeg(args)
    if rc != 0 or not out.exists():
        return {"error": f"Filigrane échoué : {err[-300:]}"}
    return {"success": True, "path": str(out), "size_human": _fmt_size(out.stat().st_size)}


def gif_optimize(gif_path: str, fps: int = 10, width: int = None,
                 colors: int = 128, output_path: str = None) -> dict:
    """Optimise un GIF existant (réduit fps/couleurs/taille) via palette ffmpeg."""
    src = Path(gif_path)
    if not src.exists():
        return {"error": f"Fichier introuvable : {gif_path}"}
    out = Path(output_path) if output_path else (_VIDEO_DIR / f"{src.stem}_opt_{uuid.uuid4().hex[:8]}.gif")
    out.parent.mkdir(parents=True, exist_ok=True)
    scale = f"scale={width}:-1:flags=lanczos," if width else ""
    vf = (f"fps={fps},{scale}split[s0][s1];"
          f"[s0]palettegen=max_colors={colors}[p];[s1][p]paletteuse")
    args = ["-i", str(src), "-vf", vf, "-loop", "0", str(out)]
    rc, err = _run_ffmpeg(args)
    if rc != 0 or not out.exists():
        return {"error": f"Optimisation échouée : {err[-300:]}"}
    orig = src.stat().st_size
    new = out.stat().st_size
    ratio = round((1 - new / orig) * 100, 1) if orig > 0 else 0
    return {"success": True, "path": str(out),
            "original_size": _fmt_size(orig), "new_size": _fmt_size(new),
            "reduction_pct": ratio}


# ══════════════════════════════════════════════════════════════════════════════
#  Boîte à outils AUDIO (ffmpeg embarqué) — v2.35
# ══════════════════════════════════════════════════════════════════════════════
_AUDIO_CODECS = {
    "mp3": "libmp3lame", "wav": "pcm_s16le", "ogg": "libvorbis",
    "flac": "flac", "aac": "aac", "m4a": "aac", "opus": "libopus",
}


def audio_info(path: str) -> dict:
    """Métadonnées audio : durée, débit, fréquence d'échantillonnage, canaux, taille."""
    p = Path(path)
    if not p.exists():
        return {"error": f"Fichier introuvable : {path}"}
    info = {"filename": p.name, "size_bytes": p.stat().st_size,
            "size_human": _fmt_size(p.stat().st_size),
            "format": p.suffix.lstrip(".").upper()}
    try:
        try:
            from moviepy import AudioFileClip
        except ImportError:
            from moviepy.editor import AudioFileClip
        with AudioFileClip(str(p)) as clip:
            info["duration_sec"] = round(clip.duration, 2)
            info["sample_rate"] = int(getattr(clip, "fps", 0) or 0)
            info["channels"] = int(getattr(clip, "nchannels", 0) or 0)
            if clip.duration and clip.duration > 0:
                info["bitrate_kbps"] = round((p.stat().st_size * 8) / clip.duration / 1000, 1)
            mm, ss = divmod(int(clip.duration), 60)
            info["duration_human"] = f"{mm}:{ss:02d}"
    except Exception as e:
        info["info_error"] = str(e)
    return info


def audio_extract(video_path: str, fmt: str = "mp3", bitrate: str = "192k",
                  output_path: str = None) -> dict:
    """Extrait la piste audio d'une vidéo vers un fichier audio (mp3/wav/aac…)."""
    src = Path(video_path)
    if not src.exists():
        return {"error": f"Fichier introuvable : {video_path}"}
    fmt = (fmt or "mp3").lower().lstrip(".")
    codec = _AUDIO_CODECS.get(fmt, "libmp3lame")
    out = Path(output_path) if output_path else src.with_name(f"{src.stem}.{fmt}")
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["-i", str(src), "-vn", "-acodec", codec]
    if fmt not in ("wav", "flac"):
        args += ["-b:a", bitrate]
    args += [str(out)]
    rc, err = _run_ffmpeg(args)
    if rc != 0 or not out.exists():
        return {"error": f"Extraction audio échouée : {err[-300:]}"}
    return {"success": True, "path": str(out), "format": fmt.upper(),
            "size_human": _fmt_size(out.stat().st_size)}


def audio_convert(path: str, fmt: str = "mp3", bitrate: str = "192k",
                  sample_rate: int = None, output_path: str = None) -> dict:
    """Convertit un fichier audio vers un autre format (mp3/wav/ogg/flac/aac/opus)."""
    src = Path(path)
    if not src.exists():
        return {"error": f"Fichier introuvable : {path}"}
    fmt = (fmt or "mp3").lower().lstrip(".")
    codec = _AUDIO_CODECS.get(fmt)
    if not codec:
        return {"error": f"Format non supporté : {fmt}. Choix : {', '.join(_AUDIO_CODECS)}"}
    out = Path(output_path) if output_path else src.with_name(f"{src.stem}.{fmt}")
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["-i", str(src), "-vn", "-acodec", codec]
    if fmt not in ("wav", "flac"):
        args += ["-b:a", bitrate]
    if sample_rate:
        args += ["-ar", str(sample_rate)]
    args += [str(out)]
    rc, err = _run_ffmpeg(args)
    if rc != 0 or not out.exists():
        return {"error": f"Conversion échouée : {err[-300:]}"}
    return {"success": True, "path": str(out), "format": fmt.upper(),
            "size_human": _fmt_size(out.stat().st_size)}


def audio_trim(path: str, start: float = 0, end: float = None,
               duration: float = None, output_path: str = None) -> dict:
    """Découpe un segment audio (start/end en secondes, ou start + duration)."""
    src = Path(path)
    if not src.exists():
        return {"error": f"Fichier introuvable : {path}"}
    out = Path(output_path) if output_path else src.with_name(f"{src.stem}_coupe{src.suffix}")
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["-ss", str(start), "-i", str(src)]
    if duration is not None:
        args += ["-t", str(duration)]
    elif end is not None:
        args += ["-t", str(max(0.0, float(end) - float(start)))]
    args += [str(out)]
    rc, err = _run_ffmpeg(args)
    if rc != 0 or not out.exists():
        return {"error": f"Découpe audio échouée : {err[-300:]}"}
    return {"success": True, "path": str(out), "size_human": _fmt_size(out.stat().st_size)}


def audio_merge(paths: list, output_path: str = None, fmt: str = "mp3") -> dict:
    """Concatène plusieurs fichiers audio bout à bout (gère des formats différents)."""
    srcs = [Path(p) for p in (paths or [])]
    missing = [str(p) for p in srcs if not p.exists()]
    if missing:
        return {"error": f"Fichier(s) introuvable(s) : {', '.join(missing)}"}
    if len(srcs) < 2:
        return {"error": "Fournir au moins 2 fichiers audio."}
    fmt = (fmt or "mp3").lower().lstrip(".")
    codec = _AUDIO_CODECS.get(fmt, "libmp3lame")
    out = Path(output_path) if output_path else (srcs[0].with_name(f"fusion_audio.{fmt}"))
    out.parent.mkdir(parents=True, exist_ok=True)
    args = []
    for s in srcs:
        args += ["-i", str(s)]
    streams = "".join(f"[{i}:a]" for i in range(len(srcs)))
    filt = f"{streams}concat=n={len(srcs)}:v=0:a=1[out]"
    args += ["-filter_complex", filt, "-map", "[out]", "-acodec", codec]
    if fmt not in ("wav", "flac"):
        args += ["-b:a", "192k"]
    args += [str(out)]
    rc, err = _run_ffmpeg(args)
    if rc != 0 or not out.exists():
        return {"error": f"Fusion audio échouée : {err[-300:]}"}
    return {"success": True, "path": str(out), "merged": len(srcs),
            "size_human": _fmt_size(out.stat().st_size)}


def audio_volume(path: str, factor: float = None, gain_db: float = None,
                 normalize: bool = False, output_path: str = None) -> dict:
    """Ajuste le volume (facteur ex 1.5, ou gain_db ex +6/-6) ou normalise (loudnorm)."""
    src = Path(path)
    if not src.exists():
        return {"error": f"Fichier introuvable : {path}"}
    out = Path(output_path) if output_path else src.with_name(f"{src.stem}_vol{src.suffix}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if normalize:
        af = "loudnorm"
    elif gain_db is not None:
        af = f"volume={gain_db}dB"
    elif factor is not None:
        af = f"volume={factor}"
    else:
        return {"error": "Préciser factor, gain_db ou normalize=true."}
    args = ["-i", str(src), "-filter:a", af, str(out)]
    rc, err = _run_ffmpeg(args)
    if rc != 0 or not out.exists():
        return {"error": f"Réglage du volume échoué : {err[-300:]}"}
    return {"success": True, "path": str(out), "applied": af,
            "size_human": _fmt_size(out.stat().st_size)}


def screen_record_gif(duration: float = 5, fps: int = 10, region: list = None,
                      output_path: str = None) -> dict:
    """
    Enregistre l'écran en GIF (via mss frame capture + PIL).
    region = [x, y, w, h] ou None pour l'écran principal.
    """
    try:
        import mss as _mss
        from PIL import Image as _Img
        import time as _t
    except ImportError:
        return {"error": "Dépendance manquante (mss/PIL). pip install mss"}

    out = Path(output_path) if output_path else (_VIDEO_DIR / f"screenrec_{uuid.uuid4().hex[:8]}.gif")
    out.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    frame_interval = 1.0 / fps
    n_frames = int(duration * fps)
    try:
        with _mss.mss() as sct:
            if region and len(region) == 4:
                mon = {"left": region[0], "top": region[1], "width": region[2], "height": region[3]}
            else:
                mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            for _ in range(n_frames):
                t0 = _t.time()
                shot = sct.grab(mon)
                img = _Img.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                # Downscale to max 800px wide for reasonable GIF size
                if img.width > 800:
                    ratio = 800 / img.width
                    img = img.resize((800, int(img.height * ratio)), _Img.LANCZOS)
                frames.append(img)
                elapsed = _t.time() - t0
                if elapsed < frame_interval:
                    _t.sleep(frame_interval - elapsed)
        if not frames:
            return {"error": "Aucune frame capturée"}
        frames[0].save(str(out), save_all=True, append_images=frames[1:],
                       duration=int(frame_interval * 1000), loop=0, optimize=True)
        return {"success": True, "path": str(out), "frames": len(frames),
                "size_human": _fmt_size(out.stat().st_size)}
    except Exception as e:
        return {"error": str(e)}
