"""Résolution du modèle et de la confidentialité pour un tour Marvin."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cloud_routing
from agent_routing import (
    detect_profile,
    get_cloud_config,
    is_cloud_model,
    is_local_only_lockdown,
    is_sensitive_request,
    is_ultra_unrestricted,
    refresh_model_cache,
)
from config import DEFAULT_MODEL, MODEL_PROFILES


@dataclass(slots=True)
class ModelConfig:
    profile_name: str
    active_model: str
    temperature: float
    label: str
    local_fallback_model: str
    lockdown: bool
    ultra_cloud_only: bool
    sensitive: bool

    def event(self) -> dict[str, Any]:
        return {
            "type": "model_info",
            "profile": self.profile_name,
            "model": self.active_model,
            "label": self.label,
        }


def _manual_temperature(model: str) -> float:
    if any(marker in model for marker in (":3b", ":1b", ":2b", "3b", "1b")):
        return 0.3
    if any(marker in model for marker in (":7b", ":8b", "7b", "8b")):
        return 0.2
    if any(marker in model for marker in (":14b", ":13b", ":12b", "14b")):
        return 0.2
    return 0.3


async def resolve_model_config(
    messages: list[dict[str, Any]],
    user_query: str,
    requested_model: str | None,
    cortex_plan: dict[str, Any],
) -> ModelConfig:
    """Résout une fois le modèle du tour et son repli, avant la boucle d'outils."""
    lockdown = is_local_only_lockdown()
    ultra = (not lockdown) and is_ultra_unrestricted()

    if not requested_model or requested_model == "auto":
        await refresh_model_cache()
        profile_name, active_model, temperature = detect_profile(messages)
        cloud_enabled, cloud_overrides = get_cloud_config()
        if cloud_enabled and not lockdown and profile_name in cloud_overrides:
            normalized_text = cloud_routing.strip_accents((user_query or "").lower())
            if ultra or not is_sensitive_request(messages, normalized_text):
                configured = cloud_overrides[profile_name]
                installed = cloud_routing.list_installed_cloud_models()
                active_model = (
                    configured
                    if configured in installed
                    else (cloud_routing.pick_best_cloud_model("general") or active_model)
                )
                task = cloud_routing.detect_task(user_query)
                if task:
                    active_model = cloud_routing.pick_best_cloud_model(task) or active_model
    else:
        active_model = requested_model
        profile_name = "manual"
        if lockdown and is_cloud_model(active_model):
            active_model = MODEL_PROFILES.get("agent", {}).get("model") or DEFAULT_MODEL
            profile_name = "agent"
        temperature = _manual_temperature(active_model)

    if ultra:
        cloud_need = (
            "vision"
            if profile_name == "vision"
            else (
                cloud_routing.detect_task(user_query)
                or {"analysis": "reasoning", "agent": "agentic"}.get(profile_name, "general")
            )
        )
        active_model = cloud_routing.require_cloud_model(
            cloud_need,
            requested_model=active_model if is_cloud_model(active_model) else None,
        )

    privacy = cortex_plan["resolved"]["privacy"]
    sensitive = is_sensitive_request(
        messages, cloud_routing.strip_accents((user_query or "").lower())
    )
    if (
        not ultra
        and is_cloud_model(active_model)
        and (privacy == "local" or (privacy == "hybrid_redacted" and sensitive))
    ):
        active_model = (
            MODEL_PROFILES.get(profile_name, {}).get("model")
            or MODEL_PROFILES.get("agent", {}).get("model")
            or DEFAULT_MODEL
        )
        if profile_name == "manual":
            profile_name = "agent"

    local_fallback_model = (
        MODEL_PROFILES.get(profile_name, {}).get("model")
        or MODEL_PROFILES.get("agent", {}).get("model")
        or DEFAULT_MODEL
    )
    label = MODEL_PROFILES.get(profile_name, {}).get("label", f"🎯 {active_model}")
    if ultra:
        label = f"☁️ Cloud strict · {active_model}"
    elif profile_name == "manual":
        label = f"🎯 {active_model}"

    return ModelConfig(
        profile_name=profile_name,
        active_model=active_model,
        temperature=temperature,
        label=label,
        local_fallback_model=local_fallback_model,
        lockdown=lockdown,
        ultra_cloud_only=ultra,
        sensitive=sensitive,
    )
