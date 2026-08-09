"""Regressions de résolution modèle et confidentialité du Runner."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_model_config as models


def _plan(privacy: str = "auto") -> dict:
    return {"resolved": {"privacy": privacy}}


async def _run() -> None:
    messages = [{"role": "user", "content": "écris un script"}]

    with (
        patch.object(models, "is_local_only_lockdown", return_value=False),
        patch.object(models, "is_ultra_unrestricted", return_value=False),
        patch.object(models, "is_cloud_model", return_value=False),
        patch.object(models, "is_sensitive_request", return_value=False),
    ):
        manual = await models.resolve_model_config(messages, "script", "qwen2.5:14b", _plan())
    assert manual.profile_name == "manual"
    assert manual.active_model == "qwen2.5:14b"
    assert manual.temperature == 0.2
    assert manual.event()["label"] == "🎯 qwen2.5:14b"

    with (
        patch.object(models, "is_local_only_lockdown", return_value=True),
        patch.object(models, "is_ultra_unrestricted", return_value=True),
        patch.object(models, "is_cloud_model", side_effect=lambda name: name.endswith(":cloud")),
        patch.object(models, "is_sensitive_request", return_value=True),
    ):
        locked = await models.resolve_model_config(messages, "secret", "glm:cloud", _plan())
    assert locked.profile_name == "agent"
    assert not locked.active_model.endswith(":cloud")
    assert locked.lockdown is True and locked.ultra_cloud_only is False

    with (
        patch.object(models, "is_local_only_lockdown", return_value=False),
        patch.object(models, "is_ultra_unrestricted", return_value=True),
        patch.object(models, "is_cloud_model", side_effect=lambda name: name.endswith(":cloud")),
        patch.object(models, "is_sensitive_request", return_value=True),
        patch.object(models.cloud_routing, "detect_task", return_value="coding"),
        patch.object(models.cloud_routing, "require_cloud_model", return_value="kimi:cloud") as require,
    ):
        ultra = await models.resolve_model_config(messages, "code sensible", "local:14b", _plan("local"))
    assert ultra.active_model == "kimi:cloud"
    assert ultra.label == "Cloud prioritaire · kimi:cloud"
    ultra_event = ultra.event()
    assert ultra_event["provider"] == "ollama_cloud"
    assert ultra_event["privacyMode"] == "ultra_cloud"
    assert ultra_event["cloudOnly"] is True
    assert ultra_event["cloudPreferred"] is True
    assert ultra_event["degraded"] is False
    assert ultra_event["sensitive"] is True
    require.assert_called_once_with("coding", requested_model=None)

    with (
        patch.object(models, "is_local_only_lockdown", return_value=False),
        patch.object(models, "is_ultra_unrestricted", return_value=True),
        patch.object(models, "is_cloud_model", side_effect=lambda name: name.endswith(":cloud")),
        patch.object(models, "is_sensitive_request", return_value=True),
        patch.object(models.cloud_routing, "detect_task", return_value="coding"),
        patch.object(
            models.cloud_routing,
            "require_cloud_model",
            side_effect=models.cloud_routing.CloudOnlyModelUnavailable("offline"),
        ),
    ):
        ultra_local = await models.resolve_model_config(
            messages, "code sensible", "local:14b", _plan("local")
        )
    assert ultra_local.active_model == ultra_local.local_fallback_model
    ultra_local_event = ultra_local.event()
    assert ultra_local_event["privacyPreset"] == "ultra"
    assert ultra_local_event["provider"] == "ollama_local"
    assert ultra_local_event["cloudOnly"] is False
    assert ultra_local_event["degraded"] is True
    assert ultra_local_event["continuityState"] == "local_continuity"

    with (
        patch.object(models, "is_local_only_lockdown", return_value=False),
        patch.object(models, "is_ultra_unrestricted", return_value=False),
        patch.object(models, "is_cloud_model", side_effect=lambda name: name.endswith(":cloud")),
        patch.object(models, "is_sensitive_request", return_value=True),
    ):
        private = await models.resolve_model_config(messages, "secret", "glm:cloud", _plan("local"))
    assert private.profile_name == "agent"
    assert not private.active_model.endswith(":cloud")
    private_event = private.event()
    assert private_event["provider"] == "ollama_local"
    assert private_event["privacyMode"] == "sensitive_local"

    escalated_event = private.event(
        profile_name="agent",
        active_model="glm:cloud",
        label="Compétence",
    )
    assert escalated_event["profile"] == "agent"
    assert escalated_event["provider"] == "ollama_cloud"
    assert escalated_event["label"] == "Compétence"

    refresh = AsyncMock(return_value=None)
    with (
        patch.object(models, "is_local_only_lockdown", return_value=False),
        patch.object(models, "is_ultra_unrestricted", return_value=False),
        patch.object(models, "refresh_model_cache", refresh),
        patch.object(models, "detect_profile", return_value=("agent", "local:14b", 0.2)),
        patch.object(models, "get_cloud_config", return_value=(True, {"agent": "general:cloud"})),
        patch.object(models, "is_sensitive_request", return_value=False),
        patch.object(models, "is_cloud_model", side_effect=lambda name: name.endswith(":cloud")),
        patch.object(models.cloud_routing, "list_installed_cloud_models", return_value=["general:cloud"]),
        patch.object(models.cloud_routing, "detect_task", return_value="coding"),
        patch.object(models.cloud_routing, "pick_best_cloud_model", return_value="coder:cloud"),
    ):
        automatic = await models.resolve_model_config(messages, "script", "auto", _plan())
    assert automatic.active_model == "coder:cloud"
    refresh.assert_awaited_once()

    with (
        patch.object(models, "is_local_only_lockdown", return_value=False),
        patch.object(models, "is_ultra_unrestricted", return_value=False),
        patch.object(models, "refresh_model_cache", AsyncMock(return_value=None)),
        patch.object(models, "detect_profile", return_value=("agent", "local:14b", 0.2)),
        patch.object(models, "get_cloud_config", return_value=(True, {"agent": "old:cloud"})),
        patch.object(models, "is_sensitive_request", return_value=False),
        patch.object(models, "is_cloud_model", side_effect=lambda name: name.endswith(":cloud")),
        patch.object(
            models.cloud_routing,
            "list_installed_cloud_models",
            return_value=["old:cloud", "kimi-k3:cloud"],
        ),
        patch.object(models.cloud_routing, "detect_task", return_value=None),
        patch.object(
            models.cloud_routing,
            "pick_best_cloud_model",
            return_value="kimi-k3:cloud",
        ) as pick_best,
    ):
        general = await models.resolve_model_config(
            [{"role": "user", "content": "Bonjour Marvin"}],
            "Bonjour Marvin",
            "auto",
            _plan(),
        )
    assert general.active_model == "kimi-k3:cloud"
    pick_best.assert_called_once_with("agentic")


def main() -> int:
    asyncio.run(_run())
    agent_source = (BACKEND / "agent.py").read_text(encoding="utf-8-sig")
    assert "_local_fallback_model = _agent_local" in agent_source
    assert "_model_config.event(" in agent_source
    for frontend in (
        ROOT / "lib" / "contexts" / "ChatContext.jsx",
        ROOT / "lib" / "hooks" / "useSecretary.js",
    ):
        source = frontend.read_text(encoding="utf-8-sig")
        for field in ("provider", "privacyMode", "privacyPreset", "cloudOnly", "sensitive"):
            assert field in source
    import agent
    assert callable(agent._resolve_model_config)
    print("Agent Model Config OK - auto, manuel, local, Ultra Cloud et continuité.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
