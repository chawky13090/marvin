"""Régressions déterministes Model Market et Research Swarm, sans appel cloud."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import cortex
import cloud_routing
import model_market
import research_swarm
import tools


def main() -> int:
    models = [
        "deepseek-v4:cloud", "qwen3.5:cloud", "glm-5:cloud",
        "nemotron:cloud", "mistral-large:cloud",
    ]
    with (
        patch.object(model_market.cloud_routing, "list_installed_cloud_models", return_value=models),
        patch.object(model_market.cloud_routing, "get_model_capabilities", return_value={}),
        patch.object(model_market, "list_observations", return_value=[]),
    ):
        catalog = model_market.catalog("research")
        assert len(catalog["models"]) == 5
        assert catalog["policy"] == "passive_real_calls_only"
        selected = model_market.recommend("research", count=5, distinct_families=True)
        assert len(selected) == 5
        assert len({item["family"] for item in selected}) == 5
        assert model_market.recommend("verification")[0]["family"] == "mistral"

    role_models = [
        "deepseek-v4-pro:cloud", "glm-5.2:cloud", "kimi-k2.7-code:cloud",
        "minimax-m3:cloud", "qwen3.5:397b-cloud",
        "mistral-large-3:675b-cloud", "nemotron-3-super:cloud",
    ]
    with (
        patch.object(model_market.cloud_routing, "list_installed_cloud_models", return_value=role_models),
        patch.object(model_market.cloud_routing, "get_model_capabilities", return_value={}),
        patch.object(model_market, "list_observations", return_value=[]),
    ):
        assert model_market.recommend("reasoning")[0]["family"] == "deepseek"
        assert model_market.recommend("agentic")[0]["model"] == "minimax-m3:cloud"
        assert model_market.recommend("code_implementation")[0]["family"] == "kimi"
        assert model_market.recommend("code_architecture")[0]["family"] == "glm"
        assert model_market.recommend("vision")[0]["model"] == "minimax-m3:cloud"
        assert model_market.recommend("multilingual")[0]["family"] == "qwen"

    failed_kimi = [{
        "at": "2026-07-16T00:00:00+00:00",
        "model": "kimi-k2.7-code:cloud",
        "family": "kimi",
        "need": "code",
        "success": False,
        "duration_ms": 600000,
        "phase": "implementation",
    }]
    with (
        patch.object(model_market.cloud_routing, "list_installed_cloud_models", return_value=role_models),
        patch.object(model_market.cloud_routing, "get_model_capabilities", return_value={}),
        patch.object(model_market, "list_observations", return_value=failed_kimi),
    ):
        assert model_market.recommend("code_implementation")[0]["family"] == "glm"

    assert cloud_routing.detect_task("Recherche web avec sources officielles") == "research"
    assert cloud_routing.detect_task("Crée une présentation PowerPoint") == "productivity"
    assert cloud_routing.detect_task("Traduis ce texte en allemand") == "multilingual"
    assert cloud_routing.detect_task("Compare plusieurs architectures") == "reasoning"
    assert cloud_routing.detect_task("Crée un workflow en plusieurs étapes") == "agentic"
    assert cloud_routing.is_cloud_model("gemma4:e4b") is True

    with (
        patch.object(model_market.cloud_routing, "list_installed_cloud_models", return_value=role_models),
        patch.object(model_market.cloud_routing, "get_cloud_config", return_value=(True, {})),
        patch.object(model_market, "_auto_sync_enabled", return_value=True),
        patch.object(model_market, "pull_cloud_model", return_value={"success": True, "model": "x:cloud"}),
    ):
        fleet = model_market.fleet_status()
        assert any(item["model"].startswith("mistral-large-3") for item in fleet["recommended"])
        sync = asyncio.run(model_market.sync_recommended_cloud_models())
        assert sync["success"] is True
    try:
        model_market._validate_cloud_model_name("../../bad")
        raise AssertionError("Le nom dangereux aurait dû être refusé.")
    except ValueError:
        pass

    market_rows = [
        {"model": model, "family": model.split("-", 1)[0].split(":", 1)[0], "score": 70 - index}
        for index, model in enumerate(models)
    ]
    with (
        patch.object(research_swarm.cloud_routing, "get_cloud_config", return_value=(True, {})),
        patch.object(research_swarm.cloud_routing, "is_local_only_lockdown", return_value=False),
        patch.object(research_swarm.cloud_routing, "is_sensitive_text", return_value=False),
        patch.object(research_swarm.model_market, "recommend", return_value=market_rows),
    ):
        plan = research_swarm.build_plan("Comparer deux architectures publiques")
        assert len(plan["cells"]) == 5
        assert len({cell["family"] for cell in plan["cells"]}) == 5
        assert "official documentation" in plan["cells"][0]["query"]
        focused_query = research_swarm._search_query(
            "Recherche la documentation officielle actuelle puis crée un script Bash pour Zabbix Server HTTPS Debian 13",
            "sources_primaires",
        )
        assert focused_query.startswith("Bash Zabbix Server HTTPS Debian 13")
        zabbix_priority = research_swarm._source_priority(
            {"url": "https://www.zabbix.com/documentation/current/", "title": "Documentation"},
            "Installer Zabbix sur Debian 13",
        )
        generic_priority = research_swarm._source_priority(
            {"url": "https://example.net/article", "title": "Article"},
            "Installer Zabbix sur Debian 13",
        )
        assert zabbix_priority > generic_priority

    with patch.object(research_swarm.cloud_routing, "get_cloud_config", return_value=(False, {})):
        error, _ = research_swarm.validate_runtime("Question publique")
        assert "cloud" in error.lower()

    swarm = cortex.compile_contract("Recherche cette technologie", {"review": "swarm"})
    assert swarm["forced_tools"] == ["ai_research_swarm"]
    assert "ai_research_swarm" in tools.TOOLS_REGISTRY
    assert "ai_research_swarm" in {item["function"]["name"] for item in tools.TOOLS_SPEC}
    print("Model Market OK - scorecards passives, diversité des familles et contrat Research Swarm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
