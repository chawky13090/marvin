"""Régressions déterministes Cortex Search, sans appel Ollama Cloud."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import cortex
import cortex_search
import tools


def main() -> int:
    plan = cortex.compile_contract("Compare plusieurs stratégies", {"review": "search"})
    assert plan["resolved"]["review"] == "search"
    assert plan["forced_tools"] == ["ai_cortex_search"]

    models = [
        "deepseek-v4:cloud",
        "qwen3.5:cloud",
        "glm-5:cloud",
        "nemotron:cloud",
        "mistral-large:cloud",
    ]
    with (
        patch.object(cortex_search.cloud_routing, "get_cloud_config", return_value=(True, {})),
        patch.object(cortex_search.cloud_routing, "is_local_only_lockdown", return_value=False),
        patch.object(cortex_search.cloud_routing, "is_sensitive_text", return_value=False),
        patch.object(cortex_search.cloud_routing, "list_distinct_cloud_models", return_value=models),
    ):
        error, selected = cortex_search.validate_runtime("Problème public")
        assert error is None
        assert selected == models

    with patch.object(cortex_search.cloud_routing, "get_cloud_config", return_value=(False, {})):
        error, _ = cortex_search.validate_runtime("Problème public")
        assert "cloud" in error.lower()

    with (
        patch.object(cortex_search.cloud_routing, "get_cloud_config", return_value=(True, {})),
        patch.object(cortex_search.cloud_routing, "is_local_only_lockdown", return_value=False),
        patch.object(cortex_search.cloud_routing, "is_sensitive_text", return_value=True),
        patch.object(cortex_search.cloud_routing, "is_ultra_unrestricted", return_value=False),
    ):
        error, _ = cortex_search.validate_runtime("Contenu sensible")
        assert "sensible" in error.lower()

    assert "ai_cortex_search" in tools.TOOLS_REGISTRY
    assert "ai_cortex_search" in {item["function"]["name"] for item in tools.TOOLS_SPEC}
    assert len(cortex_search.STRATEGIES) == 3
    assert len(cortex_search.VERIFIERS) == 5

    print("Cortex Search OK - routage explicite, confidentialité et cinq vérificateurs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
