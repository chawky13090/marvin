"""Deterministic regressions for portable local Ollama model selection."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import auto_config
import local_model_policy


def installed(name: str, gib: float) -> dict:
    return {"name": name, "size_bytes": int(gib * local_model_policy.GIB)}


def main() -> int:
    catalog = local_model_policy.load_catalog()
    malformed = dict(catalog)
    malformed["entries"] = [dict(catalog["entries"][0], name='qwen3:4b" & whoami')]
    try:
        local_model_policy.validate_catalog(malformed)
    except local_model_policy.LocalModelPolicyError:
        pass
    else:
        raise AssertionError("un nom de modèle injectant une commande doit être refusé")
    assert catalog["entries"]

    small_gpu = {
        "vendor": "nvidia", "vram_gb": 4.0, "ram_gb": 32.0,
        "ram_available_gb": 16.0, "disk_free_bytes": 40 * local_model_policy.GIB,
    }
    recommendation = local_model_policy.recommend(
        small_gpu,
        [
            installed("qwen2.5:3b", 1.8),
            installed("qwen2.5:14b", 8.4),
            installed("llava-phi3:latest", 2.7),
            installed("remote:cloud", 0),
        ],
    )
    assert recommendation["memory_budget_gb"] == 3.0
    assert recommendation["chosen"]["agent"] == "qwen2.5:3b"
    assert recommendation["chosen"]["analysis"] == "qwen2.5:3b"
    assert recommendation["chosen"]["vision"] == "llava-phi3"
    assert recommendation["portfolio"]["agent"]["recommended"] == "qwen3:4b"
    assert recommendation["portfolio"]["vision"]["recommended"] == "qwen3.5:2b"
    assert "remote:cloud" not in recommendation["installed"]
    assert all(item["disk_ready"] for item in recommendation["downloads"])

    allowed, reason = local_model_policy.override_allowed(
        "qwen2.5:14b", "agent", small_gpu,
        [installed("qwen2.5:14b", 8.4)],
    )
    assert allowed is False and "budget mémoire" in reason

    large_gpu = {**small_gpu, "vram_gb": 24.0}
    large = local_model_policy.recommend(
        large_gpu,
        [installed("qwen3:8b", 4.9), installed("qwen3.5:4b", 3.2)],
    )
    assert large["chosen"]["agent"] == "qwen3:8b"
    assert large["chosen"]["vision"] == "qwen3.5:4b"

    dynamic = local_model_policy.recommend(
        small_gpu,
        [
            {
                **installed("future-agent:2b", 2.4),
                "capabilities": ["completion", "tools", "thinking"],
                "context_tokens": 131_072,
            },
            {
                **installed("future-vision:2b", 2.3),
                "capabilities": ["completion", "vision"],
                "context_tokens": 65_536,
            },
            {
                **installed("future-coder:2b", 2.2),
                "capabilities": ["completion", "tools"],
                "context_tokens": 98_304,
            },
        ],
    )
    assert dynamic["chosen"]["agent"] == "future-agent:2b"
    assert dynamic["chosen"]["vision"] == "future-vision:2b"
    assert dynamic["portfolio"]["coding"]["selected"] == "future-coder:2b"
    assert (
        dynamic["portfolio"]["agent"]["selected_source"]
        == "ollama_runtime_metadata"
    )

    cpu = {
        "vendor": "cpu", "vram_gb": 0.0, "ram_gb": 8.0,
        "ram_available_gb": 3.0, "disk_free_bytes": 8 * local_model_policy.GIB,
    }
    cpu_plan = local_model_policy.recommend(cpu, [installed("qwen3:1.7b", 1.3)])
    assert cpu_plan["memory_budget_gb"] < 1.5
    assert all(not item["disk_ready"] for item in cpu_plan["downloads"])

    settings = {
        "auto_model_config": True,
        "perf_mode": "auto",
        "model_overrides": {
            "agent": "qwen2.5:14b",
            "analysis": "qwen2.5:14b",
        },
    }

    def get_setting(key):
        return settings.get(key)

    def set_setting(key, value):
        settings[key] = value

    profiles = {
        key: dict(value) for key, value in auto_config.MODEL_PROFILES.items()
    }
    with (
        patch.object(auto_config, "detect_hardware", return_value=small_gpu),
        patch.object(auto_config, "_installed_models", new=AsyncMock(return_value=[
            installed("qwen2.5:3b", 1.8),
            installed("qwen2.5:14b", 8.4),
            installed("llava-phi3", 2.7),
        ])),
        patch.object(auto_config, "_unload_orphan_models", new=AsyncMock()),
        patch.object(auto_config.db, "get_setting", side_effect=get_setting),
        patch.object(auto_config.db, "set_setting", side_effect=set_setting),
        patch.object(auto_config, "MODEL_PROFILES", profiles),
    ):
        applied = asyncio.run(auto_config.apply_auto_config(force=True))
    assert applied["applied"]["agent"] == "qwen2.5:3b"
    assert len(applied["rejected_overrides"]) == 2
    assert applied["recommended_to_install"]
    assert settings["auto_config"]["catalog_schema"] == "marvin.local-model-catalog/1.0"

    print("Local Model Policy OK - matériel dynamique, budget, catalogue, disque et overrides.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
