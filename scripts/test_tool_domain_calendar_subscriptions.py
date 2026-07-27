"""Régressions des abonnements iCalendar et de leur synchronisation."""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import calendar_subscriptions


class Storage:
    settings = {}
    replaced = []
    deleted = []

    @classmethod
    def get_setting(cls, key):
        return cls.settings.get(key)

    @classmethod
    def set_setting(cls, key, value):
        cls.settings[key] = value

    @classmethod
    def replace_external_events(cls, source, events):
        cls.replaced.append((source, events))
        return len(events)

    @classmethod
    def delete_events_by_source(cls, source):
        cls.deleted.append(source)


class Request:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class Events:
    def list(self, **kwargs):
        return Request(
            {
                "items": [
                    {
                        "id": "g1",
                        "summary": "Google",
                        "start": {"date": "2026-07-28"},
                        "end": {"date": "2026-07-29"},
                    }
                ]
            }
        )


class Service:
    def events(self):
        return Events()


async def main() -> None:
    Storage.settings.clear()
    Storage.replaced.clear()
    Storage.deleted.clear()

    async def synchronizer(subscription, *, storage):
        subscription["count"] = 2
        subscription["last_sync"] = "2026-07-27 23:00"
        return {"success": True, "count": 2}

    subscribed = await calendar_subscriptions.subscribe(
        {
            "url": "https://calendar.example.test/private-token/calendar.ics",
            "name": "Travail",
            "color": "#123abc",
        },
        storage=Storage,
        synchronizer=synchronizer,
    )
    assert subscribed["success"] is True
    assert "private-token" not in subscribed["subscription"]["url"]
    assert "private-token" in Storage.settings["calendar_subscriptions"][0]["url"]

    duplicate = await calendar_subscriptions.subscribe(
        {
            "url": "https://calendar.example.test/private-token/calendar.ics",
            "name": "Travail",
        },
        storage=Storage,
        synchronizer=synchronizer,
    )
    assert "error" in duplicate

    listed = await calendar_subscriptions.list_subscriptions({}, storage=Storage)
    assert listed["count"] == 1
    assert "private-token" not in listed["subscriptions"][0]["url"]

    subscription_id = Storage.settings["calendar_subscriptions"][0]["id"]
    confirmation = await calendar_subscriptions.unsubscribe(
        {"id": subscription_id}, storage=Storage
    )
    assert confirmation["requiresConfirmation"] is True
    assert not Storage.deleted
    removed = await calendar_subscriptions.unsubscribe(
        {"id": subscription_id, "confirmed": True}, storage=Storage
    )
    assert removed["success"] is True
    assert Storage.deleted == [f"ics:{subscription_id}"]

    try:
        await calendar_subscriptions._validate_remote_url(
            "http://127.0.0.1/calendar.ics"
        )
        raise AssertionError("URL locale acceptée")
    except ValueError:
        pass

    fetch_source = inspect.getsource(calendar_subscriptions.fetch_ics)
    assert "follow_redirects=False" in fetch_source
    assert "_validate_remote_url" in fetch_source
    assert "_MAX_REDIRECTS" in fetch_source

    synced_google = await calendar_subscriptions.sync_google(
        storage=Storage,
        service_factory=lambda: Service(),
        calendar_id_resolver=lambda value: "calendar@example.test",
    )
    assert synced_google["count"] == 1
    assert Storage.replaced[-1][0] == "google"
    assert Storage.replaced[-1][1][0]["all_day"] is True

    async def google_sync(**kwargs):
        return {"connected": True, "count": 1}

    all_result = await calendar_subscriptions.sync_all(
        {},
        storage=Storage,
        synchronizer=synchronizer,
        google_synchronizer=google_sync,
    )
    assert all_result["total_events"] == 1
    assert all_result["synced"] == 1

    assert tools._parse_ics is calendar_subscriptions.parse_ics
    assert (
        tools.TOOLS_REGISTRY["calendar_subscribe"]
        is tools.execute_calendar_subscribe
    )
    assert (
        tools.TOOLS_REGISTRY["calendar_unsubscribe"]
        is tools.execute_calendar_unsubscribe
    )
    assert tools.TOOLS_REGISTRY["calendar_sync"] is tools.execute_calendar_sync


if __name__ == "__main__":
    asyncio.run(main())
    print("OK - abonnements calendrier")
