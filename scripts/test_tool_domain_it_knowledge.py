"""Regressions de la base de connaissances IT extraite de tools.py."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tools
from tool_domains import it_knowledge


def _check_facade() -> None:
    expected = {
        "it_kb_search": it_knowledge.search,
        "it_kb_list": it_knowledge.list_entries,
        "it_kb_recommend": it_knowledge.recommend,
        "it_kb_add": it_knowledge.add,
    }
    for name, executor in expected.items():
        assert tools.TOOLS_REGISTRY[name] is executor


async def _check_search_and_list() -> None:
    entries = [
        {"id": "1", "name": "Zabbix", "category": "monitoring"},
        {"id": "2", "name": "Wazuh", "category": "security"},
    ]
    with (
        patch.object(it_knowledge.db, "it_kb_search", return_value=entries),
        patch.object(it_knowledge.db, "it_kb_categories", return_value=["monitoring", "security"]),
    ):
        result = await it_knowledge.search({"query": "supervision", "limit": 5})
    assert result["count"] == 2 and result["categories"] == ["monitoring", "security"]
    invalid = await it_knowledge.search({"query": "supervision", "limit": "x"})
    assert "limit" in invalid["error"]

    with (
        patch.object(it_knowledge.db, "it_kb_list", return_value=entries),
        patch.object(it_knowledge.db, "it_kb_categories", return_value=["monitoring", "security"]),
    ):
        listed = await it_knowledge.list_entries({})
    assert listed["by_category"] == {"monitoring": ["Zabbix"], "security": ["Wazuh"]}


async def _check_recommendation_and_add() -> None:
    proprietary = {
        "id": "p",
        "name": "CloudSuite",
        "category": "backup",
        "rating": 5,
        "times_used": 0,
        "pricing_model": "paid",
        "best_for": "sauvegarde cloud",
    }
    sovereign = {
        "id": "s",
        "name": "LibreVault",
        "category": "backup",
        "rating": 4,
        "times_used": 0,
        "pricing_model": "opensource",
        "best_for": "sauvegarde auto-hébergée RGPD",
        "tags": "souverain",
    }
    increment = Mock()
    with (
        patch.object(it_knowledge.db, "it_kb_search", return_value=[proprietary, sovereign]),
        patch.object(it_knowledge.db, "it_kb_increment_usage", increment),
    ):
        result = await it_knowledge.recommend(
            {"need": "sauvegarde gratuite souveraine RGPD pour mairie"}
        )
    assert result["recommendations"][0]["name"] == "LibreVault"
    assert "Priorité gratuit/open source" in result["advice"]
    assert "Priorité souveraineté/RGPD" in result["advice"]
    assert increment.call_count == 2

    with patch.object(
        it_knowledge.db,
        "it_kb_upsert",
        return_value={"id": "n", "name": "Nouveau"},
    ):
        added = await it_knowledge.add({"name": "Nouveau", "category": "network"})
    assert added["success"] is True and added["tool"]["name"] == "Nouveau"


def main() -> int:
    _check_facade()
    asyncio.run(_check_search_and_list())
    asyncio.run(_check_recommendation_and_add())
    print("Tool Domain IT Knowledge OK - facade, recherche, score et ajout.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
