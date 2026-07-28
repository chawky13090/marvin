"""État de santé léger de Marvin avec cache du sondage Ollama."""

import asyncio
import socket
import time

import httpx
from fastapi import APIRouter, Request

from app_version import APP_VERSION
from config import OLLAMA_URL
import tools
import generation_runtime

router = APIRouter()
_cache: dict = {}
_cache_lock = asyncio.Lock()
_CACHE_TTL = 15.0


def _with_runtime(result: dict, request: Request) -> dict:
    supervisor = getattr(request.app.state, "runtime_supervisor", None)
    if supervisor is None:
        return {**result, "workers": {"available": False, "total": 0, "statuses": {}}}
    snapshot = supervisor.snapshot()
    statuses: dict[str, int] = {}
    for task in snapshot["tasks"]:
        status = task["status"]
        statuses[status] = statuses.get(status, 0) + 1
    return {
        **result,
        "workers": {
            "available": True,
            "closed": snapshot["closed"],
            "total": len(snapshot["tasks"]),
            "statuses": statuses,
        },
    }


@router.get("/api/health")
async def health(request: Request):
    global _cache
    now = time.monotonic()
    if _cache and (now - _cache.get("_ts", 0)) < _CACHE_TTL:
        return _with_runtime({key: value for key, value in _cache.items() if key != "_ts"}, request)

    async with _cache_lock:
        now = time.monotonic()
        if _cache and (now - _cache.get("_ts", 0)) < _CACHE_TTL:
            return _with_runtime({key: value for key, value in _cache.items() if key != "_ts"}, request)
        ollama_ok = False
        ollama_models = []
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{OLLAMA_URL}/api/tags")
                if response.status_code == 200:
                    ollama_ok = True
                    ollama_models = [model["name"] for model in response.json().get("models", [])]
        except Exception:
            try:
                host = OLLAMA_URL.split("//")[-1].split("/")[0].split(":")[0] or "127.0.0.1"
                port = int(OLLAMA_URL.rsplit(":", 1)[-1].split("/")[0])
                with socket.create_connection((host, port), timeout=1.5):
                    ollama_ok = True
            except Exception:
                pass
        result = {
            "status": "ok",
            "ollama": ollama_ok,
            "ollama_models": ollama_models,
            "backend": "python-fastapi",
            "version": APP_VERSION,
            "tools_count": len(tools.TOOLS_REGISTRY),
            "tools_spec_count": len(tools.TOOLS_SPEC),
            "generation": generation_runtime.snapshot(),
        }
        _cache = {**result, "_ts": now}
        return _with_runtime(result, request)
