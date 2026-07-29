"""Régressions du contrat Ultra débridé cloud-only."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import cloud_routing
import tools
from api import settings as settings_api


def test_resolution() -> None:
    installed = ["deepseek-v4-pro:cloud", "qwen3.5:397b-cloud"]
    with (
        patch.object(cloud_routing, "is_ultra_unrestricted", return_value=True),
        patch.object(cloud_routing, "is_local_only_lockdown", return_value=False),
        patch.object(cloud_routing, "list_installed_cloud_models", return_value=installed),
        patch.object(cloud_routing, "pick_best_cloud_model", side_effect=lambda need, exclude=frozenset(): next((m for m in installed if m not in exclude), None)),
    ):
        assert cloud_routing.resolve_model("qwen2.5:14b", profile="agent") == installed[0]
        assert cloud_routing.resolve_model("llava-phi3", profile="vision", has_images=True) == installed[0]
        assert cloud_routing.resolve_model(installed[1], profile="agent") == installed[1]

    with (
        patch.object(cloud_routing, "is_ultra_unrestricted", return_value=True),
        patch.object(cloud_routing, "is_local_only_lockdown", return_value=False),
        patch.object(cloud_routing, "list_installed_cloud_models", return_value=[]),
        patch.object(cloud_routing, "pick_best_cloud_model", return_value=None),
    ):
        try:
            cloud_routing.resolve_model("qwen2.5:14b", profile="agent")
        except cloud_routing.CloudOnlyModelUnavailable:
            pass
        else:
            raise AssertionError("Ultra ne doit jamais revenir silencieusement au local")

    # Le coupe-circuit Hyper local reste prioritaire si la base contient un état incohérent.
    with (
        patch.object(cloud_routing, "is_ultra_unrestricted", return_value=True),
        patch.object(cloud_routing, "is_local_only_lockdown", return_value=True),
    ):
        assert cloud_routing.resolve_model("deepseek-v4-pro:cloud", local_fallback="qwen2.5:14b") == "qwen2.5:14b"


def test_internal_cloud_fallback() -> None:
    calls: list[str] = []

    class Response:
        def __init__(self, model: str):
            self.model = model

        def raise_for_status(self) -> None:
            if self.model == "deepseek-v4-pro:cloud":
                raise httpx.TimeoutException("cloud primaire indisponible")

        def json(self) -> dict:
            return {"response": "réponse cloud secondaire"}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url: str, json: dict, timeout=None):
            calls.append(json["model"])
            return Response(json["model"])

    with (
        patch.object(cloud_routing, "resolve_model", return_value="deepseek-v4-pro:cloud"),
        patch.object(cloud_routing, "is_cloud_only_mode", return_value=True),
        patch.object(cloud_routing, "require_cloud_model", return_value="glm-5.2:cloud"),
        patch("httpx.AsyncClient", Client),
    ):
        result = asyncio.run(
            tools._ollama_generate("diagnostic", timeout=30, return_metadata=True)
        )
    assert result == {
        "text": "réponse cloud secondaire",
        "model": "glm-5.2:cloud",
        "provider": "ollama_cloud",
        "privacy_preset": "ultra",
        "cloud_only": True,
    }
    assert calls == ["deepseek-v4-pro:cloud", "glm-5.2:cloud"]
    assert all(cloud_routing.is_cloud_model(model) for model in calls)


def test_atomic_presets() -> None:
    store = {
        "cloud_enabled": False,
        "cloud_overrides": {},
        "local_only_lockdown": False,
        "ultra_unrestricted": False,
        "privacy_preset": "normal",
    }

    def get_setting(key: str):
        return store.get(key)

    def set_setting(key: str, value):
        store[key] = value

    with (
        patch.object(settings_api.db, "get_setting", side_effect=get_setting),
        patch.object(settings_api.db, "set_setting", side_effect=set_setting),
        patch.object(cloud_routing, "pick_best_cloud_model", return_value="deepseek-v4-pro:cloud"),
    ):
        ultra = asyncio.run(settings_api.set_privacy_preset(settings_api.PrivacyPresetRequest(preset="ultra")))
        assert ultra["cloud_only"] is True
        assert store["cloud_enabled"] is True
        assert store["ultra_unrestricted"] is True
        assert store["privacy_preset"] == "ultra"
        assert all(cloud_routing.is_cloud_model(model) for model in store["cloud_overrides"].values())

        hyper = asyncio.run(settings_api.set_privacy_preset(settings_api.PrivacyPresetRequest(preset="hyper")))
        assert hyper["local_only_lockdown"] is True
        assert hyper["ultra_unrestricted"] is False
        assert hyper["cloud_enabled"] is False
        assert store["privacy_preset"] == "hyper"


def main() -> int:
    test_resolution()
    test_internal_cloud_fallback()
    test_atomic_presets()
    source = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
    dispatch_source = (
        ROOT / "backend" / "agent_tool_dispatch.py"
    ).read_text(encoding="utf-8")
    assert "duplicate_poll_blocked" in dispatch_source
    assert "_dispatch_tool" in source
    assert "Cloud strict · compétence" in source
    print("Cloud-only OK - chat, vision, outils internes, presets et absence de repli local.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
