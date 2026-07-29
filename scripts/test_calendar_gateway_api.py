"""Vérifie que toutes les routes agenda passent par le gateway commun."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tool_gateway
from api import calendar


async def main() -> None:
    calls = []

    async def fake_execute(name, arguments, **options):
        calls.append((name, arguments, options))
        if name == "event_update" and arguments.get("deny"):
            return tool_gateway.ToolGatewayResult(
                {"error": "refus déterministe"}, False, 403
            )
        return tool_gateway.ToolGatewayResult(
            {"success": True, "tool": name, "arguments": arguments},
            True,
        )

    original = calendar.tool_runtime.execute
    calendar.tool_runtime.execute = fake_execute
    try:
        await calendar.list_events(period="week", limit=50)
        await calendar.create_event(calendar.EventBody(title="Réunion"))
        await calendar.update_event("event-1", {"title": "Nouveau"})
        await calendar.delete_event("event-1")
        await calendar.list_calendar_subscriptions()
        await calendar.add_calendar_subscription(
            calendar.CalendarSubscriptionBody(url="https://example.com/calendar.ics")
        )
        await calendar.remove_calendar_subscription("subscription-1")
        await calendar.sync_calendar_subscriptions("subscription-1")

        assert [call[0] for call in calls] == [
            "event_list",
            "event_create",
            "event_update",
            "event_delete",
            "calendar_subscriptions",
            "calendar_subscribe",
            "calendar_unsubscribe",
            "calendar_sync",
        ]
        assert calls[3][2]["confirmed_by_ui"] is True
        assert calls[3][1] == {"id": "event-1"}
        assert calls[6][2]["confirmed_by_ui"] is True
        assert all(call[2]["source"] == "calendar_ui" for call in calls)

        try:
            await calendar.update_event("event-2", {"deny": True})
        except HTTPException as exc:
            assert exc.status_code == 403
            assert exc.detail == "refus déterministe"
        else:
            raise AssertionError("Un refus gateway doit devenir une erreur HTTP.")
    finally:
        calendar.tool_runtime.execute = original

    print("Calendar Gateway API OK - huit routes, confirmations et refus préservés.")


if __name__ == "__main__":
    asyncio.run(main())
