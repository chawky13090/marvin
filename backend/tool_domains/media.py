"""Domaine des outils de montage vidéo, GIF et audio locaux."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import video_manager
from platform_paths import expand_user_path


PathResolver = Callable[[str], str]
_resolve_path: PathResolver = expand_user_path


def configure(*, resolve_path: PathResolver) -> None:
    global _resolve_path
    _resolve_path = resolve_path


def _path(args: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = args.get(name)
        if isinstance(value, str) and value.strip():
            return _resolve_path(value.strip())
    return None


def _output(args: dict[str, Any]) -> str | None:
    return _path(args, "output_path")


async def _run(function, /, *args, **kwargs):
    return await asyncio.get_running_loop().run_in_executor(
        None, lambda: function(*args, **kwargs)
    )


async def video_info(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path")
    if not path:
        return {"error": "Paramètre 'path' requis."}
    info = await _run(video_manager.get_media_info, path)
    return info if info.get("error") else {"success": True, **info}


async def video_to_gif(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path")
    if not path:
        return {"error": "Paramètre 'path' requis."}
    return await _run(
        video_manager.video_to_gif,
        path,
        fps=int(args.get("fps", 12)),
        width=int(args.get("width", 480)),
        start=args.get("start"),
        duration=args.get("duration"),
        output_path=_output(args),
    )


async def gif_to_video(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path")
    if not path:
        return {"error": "Paramètre 'path' requis."}
    return await _run(
        video_manager.gif_to_video,
        path,
        fps=args.get("fps"),
        output_path=_output(args),
    )


async def video_trim(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path")
    if not path:
        return {"error": "Paramètre 'path' requis."}
    return await _run(
        video_manager.video_trim,
        path,
        start=float(args.get("start", 0)),
        end=float(args["end"]) if args.get("end") is not None else None,
        duration=float(args["duration"]) if args.get("duration") is not None else None,
        output_path=_output(args),
    )


async def video_compress(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path")
    if not path:
        return {"error": "Paramètre 'path' requis."}
    return await _run(
        video_manager.video_compress,
        path,
        crf=int(args.get("crf", 28)),
        scale_width=int(args["scale_width"]) if args.get("scale_width") else None,
        output_path=_output(args),
    )


async def video_resize(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path")
    if not path:
        return {"error": "Paramètre 'path' requis."}
    return await _run(
        video_manager.video_resize,
        path,
        width=int(args["width"]) if args.get("width") else None,
        height=int(args["height"]) if args.get("height") else None,
        output_path=_output(args),
    )


async def video_extract_frames(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path")
    if not path:
        return {"error": "Paramètre 'path' requis."}
    return await _run(
        video_manager.video_extract_frames,
        path,
        fps=float(args.get("fps", 1)),
        max_frames=int(args.get("max_frames", 30)),
    )


async def video_speed(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path")
    if not path:
        return {"error": "Paramètre 'path' requis."}
    return await _run(
        video_manager.video_speed,
        path,
        factor=float(args.get("factor", 2.0)),
        output_path=_output(args),
    )


async def video_watermark(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path")
    text = args.get("text", "")
    text = text.strip() if isinstance(text, str) else ""
    if not path or not text:
        return {"error": "Paramètres 'path' et 'text' requis."}
    return await _run(
        video_manager.video_add_watermark,
        path,
        text,
        position=args.get("position", "bottom-right"),
        font_size=int(args.get("font_size", 24)),
        output_path=_output(args),
    )


async def gif_optimize(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path")
    if not path:
        return {"error": "Paramètre 'path' requis."}
    return await _run(
        video_manager.gif_optimize,
        path,
        fps=int(args.get("fps", 10)),
        width=int(args["width"]) if args.get("width") else None,
        colors=int(args.get("colors", 128)),
        output_path=_output(args),
    )


async def screen_record_gif(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(
        video_manager.screen_record_gif,
        duration=min(float(args.get("duration", 5)), 20),
        fps=int(args.get("fps", 10)),
        region=args.get("region"),
        output_path=_output(args),
    )


async def audio_info(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path")
    if not path:
        return {"error": "Paramètre 'path' requis."}
    return await _run(video_manager.audio_info, path)


async def audio_extract(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path", "video_path")
    if not path:
        return {"error": "Paramètre 'path' (vidéo) requis."}
    return await _run(
        video_manager.audio_extract,
        path,
        fmt=args.get("format", "mp3"),
        bitrate=args.get("bitrate", "192k"),
        output_path=_output(args),
    )


async def audio_convert(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path")
    if not path:
        return {"error": "Paramètre 'path' requis."}
    return await _run(
        video_manager.audio_convert,
        path,
        fmt=args.get("format", "mp3"),
        bitrate=args.get("bitrate", "192k"),
        sample_rate=int(args["sample_rate"]) if args.get("sample_rate") else None,
        output_path=_output(args),
    )


async def audio_trim(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path")
    if not path:
        return {"error": "Paramètre 'path' requis."}
    return await _run(
        video_manager.audio_trim,
        path,
        start=float(args.get("start", 0)),
        end=float(args["end"]) if args.get("end") is not None else None,
        duration=float(args["duration"]) if args.get("duration") is not None else None,
        output_path=_output(args),
    )


async def audio_merge(args: dict[str, Any]) -> dict[str, Any]:
    paths = args.get("paths") or args.get("sources") or []
    if isinstance(paths, str):
        paths = [item.strip() for item in paths.replace("\n", ",").split(",") if item.strip()]
    if not isinstance(paths, list) or len(paths) < 2:
        return {"error": "Fournir au moins 2 fichiers audio dans 'paths'."}
    return await _run(
        video_manager.audio_merge,
        [_resolve_path(str(path)) for path in paths],
        fmt=args.get("format", "mp3"),
        output_path=_output(args),
    )


async def audio_volume(args: dict[str, Any]) -> dict[str, Any]:
    path = _path(args, "path")
    if not path:
        return {"error": "Paramètre 'path' requis."}
    return await _run(
        video_manager.audio_volume,
        path,
        factor=float(args["factor"]) if args.get("factor") is not None else None,
        gain_db=float(args["gain_db"]) if args.get("gain_db") is not None else None,
        normalize=bool(args.get("normalize", False)),
        output_path=_output(args),
    )
