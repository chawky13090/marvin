"""Notifications Telegram bornées avec transport et configuration injectables."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol


class Response(Protocol):
    status_code: int
    text: str


Post = Callable[..., Awaitable[Response]]

_get_setting: Callable[[str], Any] | None = None
_post: Post | None = None

_TOKEN_RE = re.compile(r"^\d{5,20}:[A-Za-z0-9_-]{20,100}$")
_CHAT_ID_RE = re.compile(r"^(?:-?\d{1,24}|@[A-Za-z][A-Za-z0-9_]{4,31})$")
_MAX_TEXT = 4096


async def _default_post(url: str, **kwargs: Any) -> Response:
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.post(url, **kwargs)


def configure(*, get_setting: Callable[[str], Any], post: Post | None = None) -> None:
    global _get_setting, _post
    _get_setting = get_setting
    _post = post or _default_post


def _require_dependencies() -> None:
    if _get_setting is None or _post is None:
        raise RuntimeError("Le domaine Telegram n'est pas configuré.")


def get_config() -> dict[str, Any]:
    _require_dependencies()
    assert _get_setting is not None
    value = _get_setting("telegram_config")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return dict(value) if isinstance(value, dict) else {}


def public_config() -> dict[str, Any]:
    config = get_config()
    return {
        "enabled": bool(config.get("enabled")),
        "chat_id": str(config.get("chat_id") or "")[:40],
        "has_token": bool(config.get("bot_token")),
    }


def _credentials() -> tuple[str, str] | tuple[None, str]:
    config = get_config()
    token = str(config.get("bot_token") or "").strip()
    chat_id = str(config.get("chat_id") or "").strip()
    if not token or not chat_id:
        return None, "Telegram non configuré (jeton du bot et chat_id requis)."
    if not _TOKEN_RE.fullmatch(token):
        return None, "Le format du jeton Telegram est invalide."
    if not _CHAT_ID_RE.fullmatch(chat_id):
        return None, "Le format du chat_id Telegram est invalide."
    return token, chat_id


async def send(text: str, *, allow_html: bool = False) -> dict[str, Any]:
    """Envoie une fois, sans retry implicite pour éviter les doublons."""
    _require_dependencies()
    message = str(text or "").strip()
    if not message:
        return {"error": "Texte du message requis."}
    credentials = _credentials()
    if credentials[0] is None:
        return {"error": credentials[1]}
    token, chat_id = credentials
    assert token is not None and _post is not None
    payload_text = message[:_MAX_TEXT]
    if not allow_html:
        payload_text = html.escape(payload_text, quote=False)
    try:
        response = await _post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": payload_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
    except Exception as exc:
        return {
            "error": "Telegram est temporairement indisponible.",
            "error_type": type(exc).__name__[:80],
        }
    if response.status_code != 200:
        return {
            "error": f"Telegram a refusé le message (HTTP {response.status_code}).",
            "status_code": response.status_code,
        }
    return {"success": True, "chars": len(payload_text)}


async def notify(text: str) -> dict[str, Any]:
    """Notification de worker best-effort, mais résultat observable."""
    try:
        if not get_config().get("enabled"):
            return {"success": False, "skipped": True, "reason": "disabled"}
        return await send(text, allow_html=True)
    except Exception as exc:
        return {
            "success": False,
            "error": "Notification Telegram indisponible.",
            "error_type": type(exc).__name__[:80],
        }


async def execute_send(args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text") or args.get("message") or "").strip()
    result = await send(text, allow_html=False)
    if result.get("error"):
        return result
    return {**result, "message": "Message envoyé sur Telegram."}
