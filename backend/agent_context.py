"""Contexte de conversation et artefacts multimodaux du moteur agentique.

Ce module sépare l'état de session de la boucle d'orchestration : compaction bornée des
anciens messages et persistance des captures jointes. Les dépendances coûteuses sont
injectables afin que le comportement soit testable sans LLM ni stockage réel.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import database as db
from config import DATA_DIR
from tool_domains import screenshots


Generate = Callable[..., Awaitable[str | None]]
AnalyzeScreenshot = Callable[[str], Awaitable[dict[str, Any]]]

_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_SAFE_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _cache_key(conversation_id: str) -> str:
    return f"convsum_{conversation_id}"


def _summary_lines(messages: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for message in messages[-40:]:
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if content and message.get("role") in ("user", "assistant"):
            speaker = "Utilisateur" if message.get("role") == "user" else "Marvin"
            lines.append(f"{speaker}: {str(content)[:500]}")
    return lines


async def summarize_overflow(
    conversation_id: str | None,
    overflow: list[dict[str, Any]],
    model: str | None = None,
    *,
    generate: Generate | None = None,
) -> str | None:
    """Compacte les anciens messages et réutilise le cache tant qu'il reste actuel."""
    if not overflow or len(overflow) < 4:
        return None

    cached: Any = None
    if conversation_id:
        try:
            cached = db.get_setting(_cache_key(conversation_id))
        except Exception:
            cached = None
    if (
        isinstance(cached, dict)
        and cached.get("summary")
        and abs(cached.get("covered", 0) - len(overflow)) < 6
    ):
        return cached["summary"]

    lines = _summary_lines(overflow)
    if not lines:
        return None
    prompt = (
        "Résume cette conversation en quelques puces FACTUELLES et utiles (décisions prises, "
        "informations importantes, préférences exprimées, tâches/sujets en cours) afin de garder "
        "le contexte. Sois bref et concret.\n\n"
        + "\n".join(lines)
        + "\n\nRÉSUMÉ :"
    )
    generator = tools._ollama_generate if generate is None else generate
    try:
        summary = (await generator(prompt, model=model, timeout=120) or "").strip()
    except Exception:
        return cached.get("summary") if isinstance(cached, dict) else None
    if summary and conversation_id:
        try:
            db.set_setting(
                _cache_key(conversation_id),
                {"covered": len(overflow), "summary": summary[:1500]},
            )
        except Exception:
            pass
    return summary[:1500] if summary else None


def _conversation_screenshot_dir(conversation_id: str, data_dir: Path) -> Path:
    if not _SAFE_CONVERSATION_ID.fullmatch(conversation_id or ""):
        raise ValueError("Identifiant de conversation invalide pour le stockage d'une capture")
    return data_dir / "screenshots" / conversation_id


async def persist_and_analyze_screenshot(
    conversation_id: str,
    data_url: str,
    *,
    data_dir: Path = DATA_DIR,
    analyze: AnalyzeScreenshot | None = None,
) -> dict[str, Any] | None:
    """Persiste une capture, l'analyse et retire le fichier si l'opération échoue."""
    file_path: Path | None = None
    try:
        header, encoded = data_url.split(",", 1)
        mime = header.split(";")[0].replace("data:", "") if ":" in header else "image/png"
        extension = _MIME_EXTENSIONS.get(mime, ".png")
        raw = base64.b64decode(encoded, validate=True)

        conversation_dir = _conversation_screenshot_dir(conversation_id, data_dir)
        conversation_dir.mkdir(parents=True, exist_ok=True)
        file_path = conversation_dir / f"{uuid.uuid4().hex}{extension}"
        file_path.write_bytes(raw)

        analyzer = screenshots.analyze if analyze is None else analyze
        analysis = await analyzer(str(file_path))
        return db.create_screenshot(
            conversation_id,
            str(file_path),
            analysis.get("caption", ""),
            analysis.get("ocr_text", ""),
        )
    except (OSError, ValueError, TypeError, KeyError, binascii.Error):
        if file_path is not None:
            file_path.unlink(missing_ok=True)
        return None
    except Exception:
        if file_path is not None:
            file_path.unlink(missing_ok=True)
        return None


def screenshot_data_urls(content_parts: list[dict[str, Any]] | None) -> list[str]:
    """Extrait uniquement les images data URL effectivement jointes au message."""
    urls: list[str] = []
    for part in content_parts or []:
        if not isinstance(part, dict) or part.get("type") not in ("image_url", "image"):
            continue
        image_url = part.get("image_url")
        nested_url = image_url.get("url", "") if isinstance(image_url, dict) else ""
        url = nested_url or part.get("url", "")
        if isinstance(url, str) and url.startswith("data:"):
            urls.append(url)
    return urls


async def persist_and_analyze_screenshots(
    conversation_id: str,
    content_parts: list[dict[str, Any]] | None,
    *,
    data_dir: Path = DATA_DIR,
    analyze: AnalyzeScreenshot | None = None,
) -> list[dict[str, Any]]:
    """Analyse les captures en parallèle; l'échec d'une image n'annule pas les autres."""
    urls = screenshot_data_urls(content_parts)
    if not urls:
        return []
    results = await asyncio.gather(
        *[
            persist_and_analyze_screenshot(
                conversation_id, url, data_dir=data_dir, analyze=analyze
            )
            for url in urls
        ],
        return_exceptions=False,
    )
    return [result for result in results if result]
