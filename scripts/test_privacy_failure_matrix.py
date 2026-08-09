"""Matrice des quatre profils sous pannes Cloud, locales et Web partielles."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_model_config as model_config
import cloud_routing
import tool_availability


LOCAL = "qualified:local"
CLOUD = "frontier:cloud"


def _plan(privacy: str = "auto") -> dict:
    return {"resolved": {"privacy": privacy}}


async def _resolve(
    preset: str,
    *,
    sensitive: bool,
    cloud_available: bool,
    local_available: bool = True,
) -> tuple[model_config.ModelConfig, dict]:
    lockdown = preset == "hyper"
    ultra = preset == "ultra"
    cloud_enabled = preset != "hyper"
    # Deliberately omit overrides for Cloud-first presets. Their dynamic model
    # market must remain authoritative even after an old override disappears.
    overrides = {"agent": CLOUD} if preset == "normal" else {}

    def require_cloud(*_args, **_kwargs) -> str:
        if not cloud_available:
            raise cloud_routing.CloudOnlyModelUnavailable("cloud offline")
        return CLOUD

    with (
        patch.object(model_config, "is_local_only_lockdown", return_value=lockdown),
        patch.object(model_config, "is_ultra_unrestricted", return_value=ultra),
        patch.object(model_config, "refresh_model_cache", AsyncMock(return_value=None)),
        patch.object(
            model_config,
            "detect_profile",
            return_value=("agent", LOCAL if local_available else "", 0.2),
        ),
        patch.object(model_config, "get_cloud_config", return_value=(cloud_enabled, overrides)),
        patch.object(
            model_config,
            "effective_local_model",
            return_value=LOCAL if local_available else "",
        ),
        patch.object(model_config, "is_sensitive_request", return_value=sensitive),
        patch.object(
            model_config,
            "is_cloud_model",
            side_effect=lambda name: str(name or "").endswith(":cloud"),
        ),
        patch.object(cloud_routing, "get_privacy_preset", return_value=preset),
        patch.object(
            cloud_routing,
            "get_privacy_resilience",
            return_value={"cloud_preferred": preset in {"cloud_max", "ultra"}},
        ),
        patch.object(
            cloud_routing,
            "list_installed_cloud_models",
            return_value=[CLOUD] if cloud_available else [],
        ),
        patch.object(
            cloud_routing,
            "pick_best_cloud_model",
            return_value=CLOUD if cloud_available else None,
        ),
        patch.object(cloud_routing, "detect_task", return_value="agentic"),
        patch.object(cloud_routing, "require_cloud_model", side_effect=require_cloud),
    ):
        resolved = await model_config.resolve_model_config(
            [{"role": "user", "content": "contenu test"}],
            "contenu test",
            "auto",
            _plan("local" if sensitive else "auto"),
        )
        return resolved, resolved.event()


async def _matrix() -> None:
    normal_public, event = await _resolve(
        "normal", sensitive=False, cloud_available=True
    )
    assert normal_public.active_model == CLOUD and event["degraded"] is False

    normal_sensitive, event = await _resolve(
        "normal", sensitive=True, cloud_available=True
    )
    assert normal_sensitive.active_model == LOCAL
    assert event["privacyMode"] == "sensitive_local"

    normal_offline, event = await _resolve(
        "normal", sensitive=False, cloud_available=False
    )
    assert normal_offline.active_model == LOCAL and event["degraded"] is False

    hyper_public, public_event = await _resolve(
        "hyper", sensitive=False, cloud_available=True
    )
    hyper_sensitive, sensitive_event = await _resolve(
        "hyper", sensitive=True, cloud_available=True
    )
    assert hyper_public.active_model == hyper_sensitive.active_model == LOCAL
    assert public_event["privacyMode"] == sensitive_event["privacyMode"] == "hyper_local"

    cloud_public, event = await _resolve(
        "cloud_max", sensitive=False, cloud_available=True
    )
    assert cloud_public.active_model == CLOUD and event["degraded"] is False

    cloud_sensitive, event = await _resolve(
        "cloud_max", sensitive=True, cloud_available=True
    )
    assert cloud_sensitive.active_model == LOCAL and event["degraded"] is False

    cloud_offline, event = await _resolve(
        "cloud_max", sensitive=False, cloud_available=False
    )
    assert cloud_offline.active_model == LOCAL
    assert event["degraded"] is True
    assert event["continuityState"] == "local_continuity"
    assert event["privacyMode"] == "cloud_max_local_continuity"

    for sensitive in (False, True):
        ultra_cloud, event = await _resolve(
            "ultra", sensitive=sensitive, cloud_available=True
        )
        assert ultra_cloud.active_model == CLOUD and event["cloudOnly"] is True

        ultra_offline, event = await _resolve(
            "ultra", sensitive=sensitive, cloud_available=False
        )
        assert ultra_offline.active_model == LOCAL
        assert event["privacyPreset"] == "ultra"
        assert event["degraded"] is True and event["cloudOnly"] is False

    try:
        await _resolve(
            "ultra",
            sensitive=False,
            cloud_available=False,
            local_available=False,
        )
    except model_config.LocalModelUnavailable as exc:
        assert "aucun modele local compatible" in str(exc).casefold()
    else:
        raise AssertionError("Ultra offline without local fallback must fail explicitly")


def _tool_failures_are_profile_independent() -> None:
    inventory = tool_availability.load_inventory()
    searxng_down = tool_availability.ConnectivitySnapshot(
        internet=True,
        services={"ollama": True, "searxng": False},
        observed_at=1.0,
    )
    local_ollama_down = tool_availability.ConnectivitySnapshot(
        internet=True,
        services={"ollama": False, "searxng": True},
        observed_at=2.0,
    )
    for _preset in ("normal", "hyper", "cloud_max", "ultra"):
        assert tool_availability.describe_availability(
            "web_search", searxng_down, inventory=inventory
        )["status"] == "unavailable"
        assert tool_availability.describe_availability(
            "calculator", searxng_down, inventory=inventory
        )["status"] == "available"
        assert tool_availability.describe_availability(
            "ai_model_council", local_ollama_down, inventory=inventory
        )["status"] == "unavailable"


def main() -> int:
    asyncio.run(_matrix())
    _tool_failures_are_profile_independent()
    print("Privacy Failure Matrix OK - 4 profils, Cloud/local/Web et provenance degradee.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
