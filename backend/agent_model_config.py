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
from config import MODEL_PROFILES, effective_local_model


class LocalModelUnavailable(RuntimeError):
    """No proven local fallback is available for the active privacy policy."""


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
    continuity_state: str = "nominal"
    switch_reason: str | None = None

    def event(
        self,
        *,
        profile_name: str | None = None,
        active_model: str | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        selected_model = active_model or self.active_model
        selected_profile = profile_name or self.profile_name
        provider = "ollama_cloud" if is_cloud_model(selected_model) else "ollama_local"
        resilience = cloud_routing.get_privacy_resilience()
        degraded = self.continuity_state != "nominal" and provider == "ollama_local"
        privacy_preset = cloud_routing.get_privacy_preset()
        if self.lockdown:
            privacy_mode = "hyper_local"
        elif degraded:
            privacy_mode = f"{privacy_preset}_local_continuity"
        elif self.ultra_cloud_only and provider == "ollama_local":
            privacy_mode = "ultra_local_continuity"
        elif self.ultra_cloud_only:
            privacy_mode = "ultra_cloud"
        elif self.sensitive and provider == "ollama_local":
            privacy_mode = "sensitive_local"
        else:
            privacy_mode = "standard"
        return {
            "type": "model_info",
            "profile": selected_profile,
            "model": selected_model,
            "label": label or self.label,
            "provider": provider,
            "privacyMode": privacy_mode,
            "privacyPreset": privacy_preset,
            "cloudPreferred": bool(resilience["cloud_preferred"]),
            "cloudOnly": self.ultra_cloud_only and provider == "ollama_cloud",
            "degraded": degraded,
            "continuityState": self.continuity_state if degraded else "nominal",
            "switchReason": self.switch_reason if degraded else None,
            "sensitive": self.sensitive,
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
    initial_cloud_unavailable = False
    privacy_preset = cloud_routing.get_privacy_preset()
    normalized_text = cloud_routing.strip_accents((user_query or "").lower())
    request_sensitive = is_sensitive_request(messages, normalized_text)

    if not requested_model or requested_model == "auto":
        await refresh_model_cache()
        profile_name, active_model, temperature = detect_profile(messages)
        cloud_enabled, cloud_overrides = get_cloud_config()
        cloud_profile_requested = privacy_preset in {"cloud_max", "ultra"}
        if (
            cloud_enabled
            and not lockdown
            and (profile_name in cloud_overrides or cloud_profile_requested)
        ):
            if ultra or not request_sensitive:
                configured = str(cloud_overrides.get(profile_name) or "")
                installed = cloud_routing.list_installed_cloud_models()
                need = (
                    cloud_routing.detect_task(user_query)
                    or {
                        "analysis": "reasoning",
                        "agent": "agentic",
                        "vision": "vision",
                    }.get(profile_name, "general")
                )
                # Les overrides de profil proviennent souvent d'un ancien preset et
                # vieillissent dès qu'un modèle Cloud supérieur est installé. En mode
                # Auto, le Model Market qualifié gagne; l'override reste un repli.
                candidate = (
                    cloud_routing.pick_best_cloud_model(need)
                    or (configured if configured in installed else active_model)
                )
                if is_cloud_model(candidate):
                    active_model = candidate
                elif privacy_preset == "cloud_max":
                    initial_cloud_unavailable = True
    else:
        active_model = requested_model
        profile_name = "manual"
        if lockdown and is_cloud_model(active_model):
            active_model = effective_local_model("agent")
            profile_name = "agent"
        temperature = _manual_temperature(active_model)

    local_fallback_model = effective_local_model(profile_name)

    if ultra:
        cloud_need = (
            "vision"
            if profile_name == "vision"
            else (
                cloud_routing.detect_task(user_query)
                or {"analysis": "reasoning", "agent": "agentic"}.get(profile_name, "general")
            )
        )
        try:
            active_model = cloud_routing.require_cloud_model(
                cloud_need,
                requested_model=active_model if is_cloud_model(active_model) else None,
            )
        except cloud_routing.CloudOnlyModelUnavailable:
            if not local_fallback_model:
                raise LocalModelUnavailable(
                    "Ollama Cloud est indisponible et aucun modele local compatible "
                    "n'est installe. Ouvrez Parametres > Modeles pour installer un repli."
                )
            active_model = local_fallback_model
            initial_cloud_unavailable = True

    privacy = cortex_plan["resolved"]["privacy"]
    sensitive = request_sensitive
    if (
        not ultra
        and is_cloud_model(active_model)
        and (privacy == "local" or (privacy == "hybrid_redacted" and sensitive))
    ):
        active_model = effective_local_model(profile_name)
        if profile_name == "manual":
            profile_name = "agent"

    if not active_model:
        raise LocalModelUnavailable(
            "Aucun modele local compatible n'est installe pour ce profil. "
            "Ouvrez Parametres > Modeles pour installer un repli qualifie."
        )

    label = MODEL_PROFILES.get(profile_name, {}).get("label", f"🎯 {active_model}")
    if initial_cloud_unavailable and privacy_preset in {"cloud_max", "ultra"}:
        label = f"Continuité locale · {active_model}"
    elif ultra:
        label = f"Cloud prioritaire · {active_model}"
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
        continuity_state=("local_continuity" if initial_cloud_unavailable else "nominal"),
        switch_reason=("cloud_model_unavailable" if initial_cloud_unavailable else None),
    )
