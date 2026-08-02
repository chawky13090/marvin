"""Matrice exécutable des profils de confidentialité et de la provenance modèle."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import agent_model_config
import cloud_routing
from api import settings as settings_api


LOCAL = "qwen2.5:14b"
CLOUD = "glm-5:cloud"


def _settings(values: dict):
    return patch.object(cloud_routing.db, "get_setting", side_effect=values.get)


def test_effective_profiles() -> None:
    cases = (
        ({"privacy_preset": "normal"}, "normal"),
        ({"privacy_preset": "cloud_max", "cloud_enabled": True}, "cloud_max"),
        (
            {
                "privacy_preset": "ultra",
                "cloud_enabled": True,
                "ultra_unrestricted": True,
            },
            "ultra",
        ),
        (
            {
                "privacy_preset": "ultra",
                "cloud_enabled": True,
                "ultra_unrestricted": True,
                "local_only_lockdown": True,
            },
            "hyper",
        ),
    )
    for values, expected in cases:
        with _settings(values):
            assert cloud_routing.get_privacy_preset() == expected

    with _settings({"privacy_preset": "cloud_max", "cloud_enabled": False}):
        assert cloud_routing.get_privacy_preset() == "normal"


def test_destination_matrix() -> None:
    installed = [CLOUD]
    normal = {
        "privacy_preset": "normal",
        "cloud_enabled": True,
        "cloud_overrides": {"agent": CLOUD},
    }
    for values in (
        normal,
        {
            "privacy_preset": "cloud_max",
            "cloud_enabled": True,
            "cloud_overrides": {"agent": CLOUD},
        },
    ):
        with (
            _settings(values),
            patch.object(cloud_routing, "list_installed_cloud_models", return_value=installed),
            patch.object(cloud_routing, "pick_best_cloud_model", return_value=CLOUD),
        ):
            assert cloud_routing.resolve_model(
                None, local_fallback=LOCAL, text_for_sensitivity="public"
            ) == CLOUD
            assert cloud_routing.resolve_model(
                None,
                local_fallback=LOCAL,
                text_for_sensitivity="mot de passe secret",
            ) == LOCAL

    with _settings(
        {
            "privacy_preset": "hyper",
            "cloud_enabled": False,
            "local_only_lockdown": True,
        }
    ):
        assert cloud_routing.resolve_model(
            CLOUD, local_fallback=LOCAL, text_for_sensitivity="public"
        ) == LOCAL

    with (
        _settings(
            {
                "privacy_preset": "ultra",
                "cloud_enabled": True,
                "ultra_unrestricted": True,
            }
        ),
        patch.object(cloud_routing, "list_installed_cloud_models", return_value=installed),
        patch.object(cloud_routing, "pick_best_cloud_model", return_value=CLOUD),
    ):
        assert cloud_routing.resolve_model(
            LOCAL,
            local_fallback=LOCAL,
            text_for_sensitivity="mot de passe secret",
        ) == CLOUD


def test_provenance_and_transition() -> None:
    model = agent_model_config.ModelConfig(
        profile_name="agent",
        active_model=CLOUD,
        temperature=0.2,
        label=CLOUD,
        local_fallback_model=LOCAL,
        lockdown=False,
        ultra_cloud_only=False,
        sensitive=False,
    )
    with patch.object(cloud_routing, "get_privacy_preset", return_value="cloud_max"):
        event = model.event()
    assert event["provider"] == "ollama_cloud"
    assert event["privacyPreset"] == "cloud_max"

    store = {
        "privacy_preset": "normal",
        "cloud_enabled": True,
        "cloud_overrides": {},
        "local_only_lockdown": False,
        "ultra_unrestricted": False,
    }
    with (
        patch.object(settings_api.db, "get_setting", side_effect=store.get),
        patch.object(settings_api.db, "set_setting", side_effect=store.__setitem__),
        patch.object(cloud_routing, "pick_best_cloud_model", return_value=CLOUD),
        patch.object(settings_api.audit, "log_action") as log_action,
    ):
        state = asyncio.run(
            settings_api.set_privacy_preset(
                settings_api.PrivacyPresetRequest(preset="cloud_max")
            )
        )
    assert state["privacy_preset"] == "cloud_max"
    assert store["privacy_preset"] == "cloud_max"
    log_action.assert_called_once()
    assert log_action.call_args.args[1] == {
        "previous": "normal",
        "requested": "cloud_max",
    }


def test_frontend_contract() -> None:
    settings_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "app" / "settings" / "page.jsx",
            ROOT / "components" / "settings" / "ModelSettingsPanel.jsx",
        )
    )
    assert "setPrivacyPreset" in settings_source
    assert ": privacyPreset;" in settings_source
    for path in (
        ROOT / "lib" / "contexts" / "ChatContext.jsx",
        ROOT / "lib" / "hooks" / "useSecretary.js",
    ):
        assert "privacyPreset: event.privacyPreset" in path.read_text(encoding="utf-8")


def main() -> int:
    test_effective_profiles()
    test_destination_matrix()
    test_provenance_and_transition()
    test_frontend_contract()
    print("Privacy model matrix OK - 4 profils, destinations, transitions et provenance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
