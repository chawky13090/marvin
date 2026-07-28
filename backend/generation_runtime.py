"""Runtime partagé des générations Ollama internes aux outils Marvin."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx


class Routing(Protocol):
    def resolve_model(
        self,
        requested_model: str | None,
        profile: str = "agent",
        local_fallback: str | None = None,
        text_for_sensitivity: str = "",
        has_images: bool = False,
    ) -> str: ...

    def is_cloud_only_mode(self) -> bool: ...

    def detect_task(self, text: str) -> str | None: ...

    def require_cloud_model(
        self,
        need: str = "general",
        *,
        requested_model: str | None = None,
        exclude: frozenset[str] = frozenset(),
    ) -> str: ...


_routing: Routing | None = None
_base_url = ""
_model_profiles: dict[str, Any] | None = None
_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], Any] = asyncio.sleep
_cloud_only_unavailable: type[Exception] = RuntimeError
_client_factory: Callable[[], httpx.AsyncClient] | None = None
_client: httpx.AsyncClient | None = None
_client_lock = threading.Lock()

_stats_lock = threading.Lock()
_stats: dict[str, Any] = {
    "total": 0,
    "succeeded": 0,
    "failed": 0,
    "fallbacks": 0,
    "retries": 0,
    "attempts": 0,
    "duration_ms": 0,
    "by_model": {},
    "last_error_type": None,
}


def configure(
    *,
    routing: Routing,
    base_url: str,
    model_profiles: dict[str, Any],
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Any] = asyncio.sleep,
    cloud_only_unavailable: type[Exception] = RuntimeError,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> None:
    global _routing, _base_url, _model_profiles, _clock, _sleep
    global _cloud_only_unavailable, _client_factory, _client
    _routing = routing
    _base_url = str(base_url).rstrip("/")
    _model_profiles = model_profiles
    _clock = clock
    _sleep = sleep
    _cloud_only_unavailable = cloud_only_unavailable
    _client_factory = client_factory or _default_client_factory
    with _client_lock:
        if _client is not None and not getattr(_client, "is_closed", False):
            raise RuntimeError(
                "Fermez le pool de génération avant de reconfigurer le runtime."
            )
        _client = None


def _require_dependencies() -> None:
    if (
        _routing is None
        or _model_profiles is None
        or not _base_url
        or _client_factory is None
    ):
        raise RuntimeError("Le runtime de génération n'est pas configuré.")


def _default_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=900.0, write=30.0, pool=10.0),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


def _get_client() -> httpx.AsyncClient:
    global _client
    assert _client_factory is not None
    with _client_lock:
        if _client is None or getattr(_client, "is_closed", False):
            _client = _client_factory()
        return _client


async def close() -> None:
    global _client
    with _client_lock:
        client = _client
        _client = None
    if client is not None and not getattr(client, "is_closed", False):
        await client.aclose()


def reset_stats() -> None:
    with _stats_lock:
        _stats.update(
            {
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "fallbacks": 0,
                "retries": 0,
                "attempts": 0,
                "duration_ms": 0,
                "by_model": {},
                "last_error_type": None,
            }
        )


def snapshot() -> dict[str, Any]:
    with _stats_lock:
        total = int(_stats["total"])
        duration_ms = int(_stats["duration_ms"])
        return {
            "total": total,
            "succeeded": int(_stats["succeeded"]),
            "failed": int(_stats["failed"]),
            "fallbacks": int(_stats["fallbacks"]),
            "retries": int(_stats["retries"]),
            "attempts": int(_stats["attempts"]),
            "average_duration_ms": round(duration_ms / total) if total else 0,
            "by_model": dict(_stats["by_model"]),
            "last_error_type": _stats["last_error_type"],
        }


def _record(
    *,
    success: bool,
    model: str | None,
    attempts: int,
    retried: bool,
    fallback_used: bool,
    duration_ms: int,
    error: Exception | None,
) -> None:
    with _stats_lock:
        _stats["total"] += 1
        _stats["succeeded" if success else "failed"] += 1
        _stats["attempts"] += attempts
        _stats["duration_ms"] += max(0, duration_ms)
        if retried:
            _stats["retries"] += 1
        if fallback_used:
            _stats["fallbacks"] += 1
        if model:
            by_model = _stats["by_model"]
            by_model[model] = int(by_model.get(model, 0)) + 1
        _stats["last_error_type"] = None if error is None else type(error).__name__[:80]


async def _call(
    *,
    model: str,
    prompt: str,
    images: list[Any] | None,
    timeout: int,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if images:
        payload["images"] = images
    client = _get_client()
    request_timeout = httpx.Timeout(
        connect=10.0,
        read=float(timeout),
        write=30.0,
        pool=10.0,
    )
    response = await client.post(
        f"{_base_url}/api/generate",
        json=payload,
        timeout=request_timeout,
    )
    response.raise_for_status()
    body = response.json()
    return str(body.get("response") or "").strip() if isinstance(body, dict) else ""


async def generate(
    prompt: str,
    model: str | None = None,
    images: list[Any] | None = None,
    timeout: int = 180,
    return_metadata: bool = False,
) -> str | dict[str, str]:
    """Génère avec un retry non-timeout et un seul repli conforme à la confidentialité."""
    _require_dependencies()
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("Le prompt de génération doit être une chaîne non vide.")
    if not isinstance(images, list) and images is not None:
        raise TypeError("images doit être une liste ou None.")
    try:
        timeout_value = int(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("Le timeout de génération doit être un entier.") from exc
    if not 5 <= timeout_value <= 900:
        raise ValueError("Le timeout de génération doit être compris entre 5 et 900 secondes.")

    assert _routing is not None and _model_profiles is not None
    started = _clock()
    primary = _routing.resolve_model(
        model,
        profile="agent",
        text_for_sensitivity=prompt,
        has_images=bool(images),
    )
    if _routing.is_cloud_only_mode():
        need = "vision" if images else (_routing.detect_task(prompt) or "general")
        try:
            light = _routing.require_cloud_model(need, exclude=frozenset({primary}))
        except _cloud_only_unavailable:
            light = None
    else:
        try:
            light = _model_profiles.get("chat", {}).get("model") or "qwen2.5:3b"
        except Exception:
            light = "qwen2.5:3b"
    light_timeout = max(30, min(timeout_value, 60))
    has_light_fallback = bool(light) and light != primary

    attempts = 0
    retried = False
    fallback_used = False
    final_model: str | None = None
    last_error: Exception | None = None
    try:
        attempts += 1
        final_model = primary
        text = await _call(
            model=primary,
            prompt=prompt,
            images=images,
            timeout=timeout_value,
        )
        result = {"text": text, "model": primary} if return_metadata else text
        _record(
            success=True,
            model=primary,
            attempts=attempts,
            retried=False,
            fallback_used=False,
            duration_ms=round((_clock() - started) * 1000),
            error=None,
        )
        return result
    except Exception as exc:
        last_error = exc
        if not isinstance(exc, httpx.TimeoutException):
            retried = True
            await _sleep(1)
            try:
                attempts += 1
                text = await _call(
                    model=primary,
                    prompt=prompt,
                    images=images,
                    timeout=timeout_value,
                )
                result = {"text": text, "model": primary} if return_metadata else text
                _record(
                    success=True,
                    model=primary,
                    attempts=attempts,
                    retried=True,
                    fallback_used=False,
                    duration_ms=round((_clock() - started) * 1000),
                    error=None,
                )
                return result
            except Exception as retry_error:
                last_error = retry_error

    if has_light_fallback:
        fallback_used = True
        final_model = light
        try:
            attempts += 1
            text = await _call(
                model=light,
                prompt=prompt,
                images=images,
                timeout=light_timeout,
            )
            result = {"text": text, "model": light} if return_metadata else text
            _record(
                success=True,
                model=light,
                attempts=attempts,
                retried=retried,
                fallback_used=True,
                duration_ms=round((_clock() - started) * 1000),
                error=None,
            )
            return result
        except Exception as fallback_error:
            last_error = fallback_error

    _record(
        success=False,
        model=final_model,
        attempts=attempts,
        retried=retried,
        fallback_used=fallback_used,
        duration_ms=round((_clock() - started) * 1000),
        error=last_error,
    )
    raise last_error if last_error else RuntimeError("Ollama indisponible")
