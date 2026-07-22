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
    assert ultra.label == "☁️ Cloud strict · kimi:cloud"
    require.assert_called_once_with("coding", requested_model=None)

    with (
        patch.object(models, "is_local_only_lockdown", return_value=False),
        patch.object(models, "is_ultra_unrestricted", return_value=False),
        patch.object(models, "is_cloud_model", side_effect=lambda name: name.endswith(":cloud")),
        patch.object(models, "is_sensitive_request", return_value=True),
    ):
        private = await models.resolve_model_config(messages, "secret", "glm:cloud", _plan("local"))
    assert private.profile_name == "agent"
    assert not private.active_model.endswith(":cloud")

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


def main() -> int:
    asyncio.run(_run())
    import agent
    assert callable(agent._resolve_model_config)
    print("Agent Model Config OK - auto, manuel, local, Ultra Cloud et façade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
