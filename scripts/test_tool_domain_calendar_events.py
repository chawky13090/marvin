"""Régressions du domaine des événements de l'agenda unifié."""

from __future__ import annotations

import asyncio
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tools
from tool_domains import calendar_events


class Storage:
    events: dict[str, dict] = {}
    deleted: list[str] = []

    @classmethod
    def reset(cls):
        cls.events = {}
        cls.deleted = []

    @classmethod
    def create_event(cls, **event):
        created = {"id": f"e{len(cls.events) + 1}", "source": "local", **event}
        cls.events[created["id"]] = created
        return deepcopy(created)

    @classmethod
    def list_events(cls, start=None, end=None, limit=200):
        return [deepcopy(value) for value in cls.events.values()][:limit]

    @classmethod
    def get_event(cls, event_id):
        value = cls.events.get(event_id)
        return deepcopy(value) if value else None

    @classmethod
    def update_event(cls, event_id, updates):
        if event_id not in cls.events:
            return None
        cls.events[event_id].update(updates)
        return deepcopy(cls.events[event_id])

    @classmethod
    def delete_event(cls, event_id):
        cls.deleted.append(event_id)
        return cls.events.pop(event_id, None) is not None


async def no_sync():
    return {"success": True}


async def main() -> None:
    Storage.reset()

    async def natural_parser(text, model=None):
        return {
            "title": "Dentiste",
            "start_at": "2026-08-20 14:00",
            "end_at": "2026-08-20 15:00",
            "all_day": False,
            "location": "Paris",
        }

    async def google_success(args):
        return {"success": True, "id": "g1", "title": args["title"]}

    local = await calendar_events.create_event(
        {"natural": "dentiste", "local_only": True},
        storage=Storage,
        natural_parser=natural_parser,
        google_ready=lambda: True,
        google_create=google_success,
        google_sync=no_sync,
    )
    assert local["success"] and local["target"] == "local"
    assert Storage.events["e1"]["start_at"] == "2026-08-20 14:00"

    invalid_end = await calendar_events.create_event(
        {
            "title": "Invalide",
            "start_at": "2026-08-20 15:00",
            "end_at": "2026-08-20 14:00",
        },
        storage=Storage,
        natural_parser=natural_parser,
        google_ready=lambda: False,
        google_create=google_success,
        google_sync=no_sync,
    )
    assert "postérieure" in invalid_end["error"]

    async def google_failure(args):
        return {"error": "quota"}

    before = len(Storage.events)
    cloud_failure = await calendar_events.create_event(
        {"title": "Cloud", "start_at": "2026-08-21 10:00"},
        storage=Storage,
        natural_parser=natural_parser,
        google_ready=lambda: True,
        google_create=google_failure,
        google_sync=no_sync,
    )
    assert cloud_failure["target"] == "google"
    assert cloud_failure["local_fallback_available"] is True
    assert len(Storage.events) == before

    limited = await calendar_events.list_events({"limit": 0}, storage=Storage)
    assert "error" in limited

    Storage.events["g-local"] = {
        "id": "g-local",
        "title": "Réunion",
        "start_at": "2026-08-20 10:00",
        "end_at": "2026-08-20 11:30",
        "source": "google",
        "external_id": "g-remote",
    }
    captured = {}

    async def google_update(args):
        captured.update(args)
        return {"success": True, "title": "Réunion"}

    moved = await calendar_events.update_event(
        {"id": "g-local", "start_at": "2026-08-20 12:00"},
        storage=Storage,
        google_update=google_update,
        google_sync=no_sync,
    )
    assert moved["target"] == "google"
    assert captured["end"] == "2026-08-20T13:30"

    async def update_failure(args):
        return {"error": "indisponible"}

    unchanged = deepcopy(Storage.events["g-local"])
    failed_update = await calendar_events.update_event(
        {"id": "g-local", "title": "Nouveau"},
        storage=Storage,
        google_update=update_failure,
        google_sync=no_sync,
    )
    assert "error" in failed_update
    assert Storage.events["g-local"] == unchanged

    Storage.events["e2"] = {
        "id": "e2",
        "title": "Réunion équipe",
        "start_at": "2026-08-22 09:00",
        "source": "local",
    }
    ambiguous = await calendar_events.delete_event(
        {"title": "réunion"},
        storage=Storage,
        google_delete=google_success,
        google_sync=no_sync,
    )
    assert ambiguous["ambiguous"] and len(ambiguous["candidates"]) == 2

    confirmation = await calendar_events.delete_event(
        {"id": "e1"},
        storage=Storage,
        google_delete=google_success,
        google_sync=no_sync,
    )
    assert confirmation["requiresConfirmation"] and not Storage.deleted
    removed = await calendar_events.delete_event(
        {"id": "e1", "confirmed": True},
        storage=Storage,
        google_delete=google_success,
        google_sync=no_sync,
    )
    assert removed["success"] and Storage.deleted == ["e1"]

    assert tools._period_range is calendar_events.period_range
    assert tools.TOOLS_REGISTRY["event_create"] is tools.execute_event_create
    assert tools.TOOLS_REGISTRY["event_delete"] is tools.execute_event_delete


if __name__ == "__main__":
    asyncio.run(main())
    print("OK - événements agenda")
