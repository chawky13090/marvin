"""Régressions de la politique autonome du portefeuille local."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import local_model_policy
import local_model_portfolio


def main() -> int:
    policy = local_model_portfolio.normalize_policy({
        "enabled": True,
        "auto_download": True,
        "download_network": "unmetered",
        "max_disk_gb": 5,
        "min_free_disk_gb": 10,
        "maintained_roles": ["chat", "agent", "coding", "unknown", "coding"],
        "delete_requires_confirmation": False,
    })
    assert policy["maintained_roles"] == ["chat", "agent", "coding"]
    assert policy["delete_requires_confirmation"] is True

    recommendation = {
        "installed": ["qwen3.5:2b"],
        "portfolio": {
            "chat": {"selected": "qwen3.5:2b"},
            "agent": {"selected": "qwen3.5:2b"},
            "coding": {"selected": None},
        },
        "downloads": [{
            "model": "qwen2.5-coder:3b",
            "size_bytes": 1_900_000_000,
            "roles": ["coding"],
            "source_url": "https://ollama.com/library/qwen2.5-coder",
        }],
        "disk_free_bytes": 30 * local_model_policy.GIB,
    }
    with patch.object(local_model_portfolio, "network_cost", return_value="unmetered"):
        evaluated = local_model_portfolio.evaluate(recommendation, policy)
    assert evaluated["auto_download_queue"] == ["qwen2.5-coder:3b"]
    assert evaluated["missing_roles"] == ["coding"]
    assert evaluated["deletion_planned"] is False

    with patch.object(local_model_portfolio, "network_cost", return_value="metered"):
        metered = local_model_portfolio.evaluate(recommendation, policy)
    assert metered["auto_download_queue"] == []
    print("Local Model Portfolio OK - rôles, budgets, réseau et absence de suppression.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
