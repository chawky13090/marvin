"""Régressions déterministes du domaine santé client."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import client_health


async def _run() -> None:
    names = (
        "billing_client_get",
        "doc_intervention_list",
        "doc_asset_list",
        "doc_document_list",
        "approval_list",
        "health_score_create",
        "health_score_history",
    )
    originals = {name: getattr(client_health.db, name) for name in names}
    try:
        client_health.db.billing_client_get = lambda _id: {"id": "c1", "name": "Test"}
        client_health.db.doc_intervention_list = lambda *_args, **_kwargs: []
        client_health.db.doc_asset_list = lambda *_args, **_kwargs: []
        client_health.db.doc_document_list = lambda *_args, **_kwargs: []
        client_health.db.approval_list = lambda *_args, **_kwargs: []
        client_health.db.health_score_create = (
            lambda _score, _items, _recommendations: {"id": "score-1"}
        )
        client_health.db.health_score_history = lambda _id, limit: [{"limit": limit}]

        computed = await client_health.execute_client_health_compute({"client_id": "c1"})
        assert computed["success"] is True
        assert computed["score_id"] == "score-1"
        assert 0 <= computed["scores"]["global"] <= 100
        assert computed["risk_level"] in ("low", "medium", "high", "critical")

        assert "limit" in (
            await client_health.execute_client_health_history(
                {"client_id": "c1", "limit": 0}
            )
        )["error"]
        history = await client_health.execute_client_health_history(
            {"client_id": "c1", "limit": 24}
        )
        assert history["history"] == [{"limit": 24}]
        assert "Statut invalide" in (
            await client_health.execute_client_recommendations_generate(
                {"client_id": "c1", "status": "unknown"}
            )
        )["error"]
        assert "Formats acceptés" in (
            await client_health.execute_client_monthly_summary_generate(
                {"client_id": "c1", "format": "html"}
            )
        )["error"]

        public_names = [
            name.removeprefix("execute_")
            for name in dir(client_health)
            if name.startswith("execute_client_")
        ]
        assert len(public_names) == 5
        for public_name in public_names:
            implementation = getattr(client_health, f"execute_{public_name}")
            assert getattr(tools, f"execute_{public_name}") is implementation
            assert tools.TOOLS_REGISTRY[public_name] is implementation
    finally:
        for name, implementation in originals.items():
            setattr(client_health.db, name, implementation)


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine santé client OK")
