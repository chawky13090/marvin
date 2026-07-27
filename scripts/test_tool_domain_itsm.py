"""Régressions déterministes du domaine ITSM."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import itsm


async def main() -> None:
    calls: list[tuple[str, str, dict]] = []

    async def fake_request(method: str, endpoint: str, **kwargs):
        calls.append((method, endpoint, kwargs))
        if endpoint == "Ticket" and method == "GET":
            return {"success": True, "data": [{"id": 7, "name": "Incident"}]}
        if endpoint == "Ticket":
            return {"success": True, "data": {"id": 8}}
        return {
            "success": True,
            "data": [{"id": 9, "name": "PC-01", "serial": "ABC"}],
        }

    listed = await itsm.ticket_list(
        {"system": "GLPI", "limit": 999}, request=fake_request
    )
    assert listed["count"] == 1
    assert calls[-1][2]["params"]["range"] == "0-99"

    confirmation = await itsm.ticket_create(
        {"title": "Panne", "description": "Diagnostic"}, request=fake_request
    )
    assert confirmation["requiresConfirmation"] is True
    assert len(calls) == 1

    invalid_urgency = await itsm.ticket_create(
        {"title": "Panne", "urgency": 9, "confirmed": True},
        request=fake_request,
    )
    assert "error" in invalid_urgency
    assert len(calls) == 1

    created = await itsm.ticket_create(
        {
            "title": "Panne",
            "description": "Diagnostic",
            "urgency": "4",
            "confirmed": True,
        },
        request=fake_request,
    )
    assert created["ticket_id"] == 8
    assert calls[-1][2]["json_body"]["input"]["urgency"] == 4

    assets = await itsm.asset_list({"limit": "bad"}, request=fake_request)
    assert assets["count"] == 1
    assert calls[-1][2]["params"]["range"] == "0-49"

    unsupported = await itsm.ticket_list(
        {"system": "servicenow"}, request=fake_request
    )
    assert "error" in unsupported
    assert tools.TOOLS_REGISTRY["itsm_ticket_list"] is tools.execute_itsm_ticket_list
    assert tools.TOOLS_REGISTRY["itsm_ticket_create"] is tools.execute_itsm_ticket_create
    assert tools.TOOLS_REGISTRY["itsm_asset_list"] is tools.execute_itsm_asset_list


if __name__ == "__main__":
    asyncio.run(main())
    print("OK - domaine ITSM")
