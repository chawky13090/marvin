"""Preuves bornées de la fenêtre de contexte réellement utilisable par Ollama.

La capacité déclarée par ``/api/show`` et l'allocation observée par ``/api/ps``
répondent à deux questions différentes. Ce module conserve cette distinction afin
que Doctor et Forge ne transforment jamais une configuration souhaitée en preuve
d'exécution.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable
from typing import Any

import httpx

from config import OLLAMA_URL


MINIMUM_AGENT_CONTEXT_TOKENS = 32_768
RECOMMENDED_AGENT_CONTEXT_TOKENS = 65_536
OLLAMA_CONTEXT_DOCUMENTATION = "https://docs.ollama.com/context-length"
OLLAMA_PS_DOCUMENTATION = "https://docs.ollama.com/api/ps"


def is_cloud_model_name(name: str) -> bool:
    normalized = str(name or "").strip().casefold()
    return normalized.endswith(":cloud") or normalized.endswith("-cloud")


def _model_aliases(name: str) -> set[str]:
    normalized = str(name or "").strip()
    if not normalized:
        return set()
    aliases = {normalized}
    if normalized.endswith(":latest"):
        aliases.add(normalized[: -len(":latest")])
    else:
        aliases.add(f"{normalized}:latest")
    return aliases


def extract_max_context_tokens(payload: dict[str, Any]) -> int:
    model_info = payload.get("model_info")
    if not isinstance(model_info, dict):
        return 0
    values = [
        int(value)
        for key, value in model_info.items()
        if str(key).endswith(".context_length")
        and isinstance(value, (int, float))
        and 0 < int(value) <= 10_000_000
    ]
    return max(values, default=0)


def _safe_positive_int(value: Any, *, maximum: int = 10_000_000) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if 0 < parsed <= maximum else 0


async def inspect_context_runtime(
    model_names: Iterable[str],
    *,
    ollama_url: str = OLLAMA_URL,
    minimum_tokens: int = MINIMUM_AGENT_CONTEXT_TOKENS,
    recommended_tokens: int = RECOMMENDED_AGENT_CONTEXT_TOKENS,
    client: Any | None = None,
) -> dict[str, Any]:
    """Inspecte les modèles demandés sans en charger un ni lancer d'inférence.

    Pour un modèle local, seule une entrée ``/api/ps`` constitue une preuve de
    l'allocation runtime. Un modèle installé mais non chargé reste ``deferred``.
    Pour Ollama Cloud, la documentation fournisseur garantit le contexte maximal;
    ``/api/show`` borne néanmoins cette capacité pour le tag exact demandé.
    """

    if minimum_tokens <= 0 or recommended_tokens < minimum_tokens:
        raise ValueError("Seuils de contexte invalides.")
    models = sorted({str(name).strip() for name in model_names if str(name).strip()})
    if not models:
        return {
            "status": "deferred",
            "minimum_tokens": minimum_tokens,
            "recommended_tokens": recommended_tokens,
            "capture_process_env_tokens": _safe_positive_int(os.getenv("OLLAMA_CONTEXT_LENGTH")),
            "capture_process_env_scope": "capture_process_only_not_ollama_runtime",
            "ollama_version": None,
            "models": [],
            "reason": "no_model_selected",
        }

    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0))
    base_url = ollama_url.rstrip("/")
    try:
        version_response, ps_response = await asyncio.gather(
            http_client.get(f"{base_url}/api/version"),
            http_client.get(f"{base_url}/api/ps"),
        )
        version_response.raise_for_status()
        ps_response.raise_for_status()
        version_payload = version_response.json()
        ps_payload = ps_response.json()
        loaded_models = ps_payload.get("models") if isinstance(ps_payload, dict) else []
        if not isinstance(loaded_models, list):
            loaded_models = []

        loaded_by_alias: dict[str, dict[str, Any]] = {}
        for item in loaded_models:
            if not isinstance(item, dict):
                continue
            loaded_name = str(item.get("name") or item.get("model") or "").strip()
            for alias in _model_aliases(loaded_name):
                loaded_by_alias[alias] = item

        semaphore = asyncio.Semaphore(4)

        async def inspect_model(name: str) -> dict[str, Any]:
            try:
                async with semaphore:
                    response = await http_client.post(
                        f"{base_url}/api/show",
                        json={"model": name, "verbose": False},
                    )
                response.raise_for_status()
                show = response.json()
            except Exception as exc:
                return {
                    "model": name,
                    "provider": "cloud" if is_cloud_model_name(name) else "local",
                    "status": "failed",
                    "evidence": "show_failed",
                    "error_type": type(exc).__name__,
                }

            max_context = extract_max_context_tokens(show if isinstance(show, dict) else {})
            cloud = is_cloud_model_name(name)
            loaded = next(
                (loaded_by_alias[alias] for alias in _model_aliases(name) if alias in loaded_by_alias),
                None,
            )
            allocated = _safe_positive_int((loaded or {}).get("context_length"))
            digest = str((loaded or {}).get("digest") or "") or None
            size = _safe_positive_int((loaded or {}).get("size"), maximum=(1 << 63) - 1)
            size_vram = _safe_positive_int(
                (loaded or {}).get("size_vram"), maximum=(1 << 63) - 1
            )
            gpu_residency_ratio = (
                round(size_vram / size, 4) if size and size_vram <= size else None
            )

            if cloud:
                effective = None
                status = "provider_declared" if max_context >= minimum_tokens else "failed"
                evidence = "cloud_provider_declared_max"
            elif loaded is not None:
                effective = allocated
                status = "verified" if effective >= minimum_tokens else "failed"
                evidence = "api_ps_allocated_context"
            else:
                effective = None
                status = "deferred" if max_context >= minimum_tokens else "failed"
                evidence = "not_loaded"

            return {
                "model": name,
                "provider": "cloud" if cloud else "local",
                "status": status,
                "evidence": evidence,
                "loaded": loaded is not None,
                "allocated_context_tokens": allocated or None,
                "max_context_tokens": max_context or None,
                "effective_context_tokens": effective,
                "meets_minimum": bool(effective and effective >= minimum_tokens),
                "meets_recommended": bool(effective and effective >= recommended_tokens),
                "digest": digest,
                "runtime_size_bytes": size or None,
                "runtime_size_vram_bytes": size_vram or None,
                "gpu_residency_ratio": gpu_residency_ratio,
                "processor_split_source": "api_ps_size_ratio" if gpu_residency_ratio is not None else None,
                "gpu_residency_scope": (
                    "ollama_reported_loaded_size_not_guaranteed_full_kv_reservation"
                    if gpu_residency_ratio is not None
                    else None
                ),
                "cloud_provider_declared_max": (max_context or None) if cloud else None,
                "cloud_client_override_absent": cloud,
                "cloud_runtime_allocation": None,
            }

        results = await asyncio.gather(*(inspect_model(name) for name in models))
        statuses = {item["status"] for item in results}
        if "failed" in statuses:
            overall = "failed"
        elif "deferred" in statuses:
            overall = "deferred"
        elif statuses == {"provider_declared"}:
            overall = "provider_declared"
        elif "provider_declared" in statuses:
            overall = "verified_with_provider_declarations"
        else:
            overall = "verified"
        return {
            "status": overall,
            "minimum_tokens": minimum_tokens,
            "recommended_tokens": recommended_tokens,
            "capture_process_env_tokens": _safe_positive_int(os.getenv("OLLAMA_CONTEXT_LENGTH")),
            "capture_process_env_scope": "capture_process_only_not_ollama_runtime",
            "ollama_version": str(version_payload.get("version") or "") or None,
            "models": results,
            "documentation": {
                "context": OLLAMA_CONTEXT_DOCUMENTATION,
                "runtime": OLLAMA_PS_DOCUMENTATION,
            },
        }
    except Exception as exc:
        return {
            "status": "failed",
            "minimum_tokens": minimum_tokens,
            "recommended_tokens": recommended_tokens,
            "capture_process_env_tokens": _safe_positive_int(os.getenv("OLLAMA_CONTEXT_LENGTH")),
            "capture_process_env_scope": "capture_process_only_not_ollama_runtime",
            "ollama_version": None,
            "models": [],
            "reason": "ollama_inspection_failed",
            "error_type": type(exc).__name__,
        }
    finally:
        if owns_client:
            await http_client.aclose()
