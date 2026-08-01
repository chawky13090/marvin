"""Idempotent background installation of allowlisted local Ollama models."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import httpx

import database as db
import local_model_policy
from config import OLLAMA_URL


_TASK: asyncio.Task | None = None
_LOCK = asyncio.Lock()
MAX_LINE_BYTES = 64 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def status() -> dict[str, Any]:
    value = db.get_setting("local_model_download_status") or {}
    return value if isinstance(value, dict) else {}


def _write(payload: dict[str, Any]) -> None:
    db.set_setting("local_model_download_status", payload)


def allowed_models() -> set[str]:
    return {
        local_model_policy.canonical_name(entry["name"])
        for entry in local_model_policy.load_catalog()["entries"]
    }


async def _pull_one(client: httpx.AsyncClient, model: str, state: dict[str, Any]) -> None:
    async with client.stream(
        "POST", f"{OLLAMA_URL}/api/pull", json={"model": model, "stream": True},
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line:
                continue
            if len(line.encode("utf-8", errors="replace")) > MAX_LINE_BYTES:
                raise RuntimeError("Réponse Ollama trop volumineuse.")
            event = json.loads(line)
            if event.get("error"):
                raise RuntimeError("Ollama a refusé le téléchargement.")
            total = max(0, int(event.get("total") or 0))
            completed = max(0, int(event.get("completed") or 0))
            state.update({
                "current": model,
                "phase": str(event.get("status") or "downloading")[:100],
                "total_bytes": total,
                "completed_bytes": min(completed, total) if total else completed,
                "updated_at": _now(),
            })
            _write(state)


async def _validate_one(client: httpx.AsyncClient, model: str) -> dict[str, Any]:
    response = await client.post(
        f"{OLLAMA_URL}/api/show", json={"model": model, "verbose": False},
    )
    response.raise_for_status()
    payload = response.json()
    capabilities = sorted({
        str(item).strip().casefold()
        for item in payload.get("capabilities") or []
        if str(item).strip()
    })
    if not capabilities:
        raise RuntimeError("Le modèle téléchargé n'expose aucune capacité vérifiable.")
    return {
        "model": model,
        "capabilities": capabilities,
        "validated": True,
        "validated_at": _now(),
    }


async def _run(models: list[str]) -> None:
    state = {
        "status": "running", "models": models, "installed": [],
        "validated": [], "failed": [], "started_at": _now(), "updated_at": _now(),
    }
    _write(state)
    async with _LOCK:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(1800.0, connect=10.0),
        ) as client:
            for model in models:
                try:
                    await _pull_one(client, model, state)
                    validation = await _validate_one(client, model)
                    state["installed"].append(model)
                    state["validated"].append(validation)
                except (httpx.HTTPError, json.JSONDecodeError, OSError, RuntimeError, ValueError) as exc:
                    state["failed"].append({
                        "model": model,
                        "error_type": type(exc).__name__,
                    })
                state["updated_at"] = _now()
                _write(state)
    state.update({
        "status": "completed" if not state["failed"] else "degraded",
        "current": None, "finished_at": _now(), "updated_at": _now(),
    })
    _write(state)
    if state["installed"]:
        try:
            import auto_config
            await auto_config.apply_auto_config(force=True)
        except Exception as exc:
            state["activation_warning"] = type(exc).__name__
            _write(state)
    try:
        import audit

        audit.log_action(
            "local_model_portfolio_download",
            {"requested_count": len(models)},
            {
                "status": state["status"],
                "installed_count": len(state["installed"]),
                "failed_count": len(state["failed"]),
            },
            source="system",
        )
    except Exception:
        pass


def start(models: list[str], *, confirmed: bool) -> dict[str, Any]:
    global _TASK
    if not confirmed:
        return {
            "requiresConfirmation": True,
            "message": "Confirme le téléchargement des modèles locaux recommandés.",
        }
    allowed = allowed_models()
    normalized = list(dict.fromkeys(
        local_model_policy.canonical_name(item) for item in models
    ))
    if not normalized or len(normalized) > 10 or any(item not in allowed for item in normalized):
        raise ValueError("Liste de modèles locaux invalide ou non autorisée.")
    if _TASK and not _TASK.done():
        return {"success": True, "status": "already_running", "download": status()}
    queued = {
        "status": "queued",
        "models": normalized,
        "completed": [],
        "failed": [],
        "current": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _write(queued)
    _TASK = asyncio.create_task(_run(normalized), name="local-model-installer")
    return {
        "success": True, "status": "queued", "models": normalized,
        "download": queued,
    }


async def shutdown() -> None:
    global _TASK
    if _TASK and not _TASK.done():
        _TASK.cancel()
        await asyncio.gather(_TASK, return_exceptions=True)
    _TASK = None
