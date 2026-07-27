"""Régressions déterministes du domaine Google Calendar."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import google_calendar


class Request:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.payload


class NotFound(Exception):
    class Response:
        status = 404

    resp = Response()


class Events:
    def __init__(self, *, fail_list=False):
        self.fail_list = fail_list
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        if self.fail_list:
            return Request(error=NotFound("absent"))
        return Request(
            {
                "items": [
                    {
                        "id": "e1",
                        "summary": "Réunion",
                        "start": {"dateTime": "2026-07-27T10:00:00+02:00"},
                        "end": {"dateTime": "2026-07-27T11:00:00+02:00"},
                    }
                ]
            }
        )

    def insert(self, **kwargs):
        self.calls.append(("insert", kwargs))
        return Request({"id": "new", **kwargs["body"]})

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return Request({})

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        return Request(
            {
                "id": "e1",
                "summary": "Avant",
                "start": {"dateTime": "2026-07-27T10:00:00+02:00"},
                "end": {"dateTime": "2026-07-27T11:00:00+02:00"},
            }
        )

    def update(self, **kwargs):
        self.calls.append(("update", kwargs))
        return Request(kwargs["body"])


class Service:
    def __init__(self, *, fail_list=False):
        self.resource = Events(fail_list=fail_list)

    def events(self):
        return self.resource


async def main() -> None:
    primary = Service(fail_list=True)
    oauth = Service()
    factory_calls = []

    def fallback_factory(prefer_oauth=False):
        factory_calls.append(prefer_oauth)
        return oauth if prefer_oauth else primary

    listed = await google_calendar.list_events(
        {
            "calendar_id": "calendar@example.test",
            "days": 500,
            "max_results": 500,
            "time_min": "2026-07-01T00:00:00+02:00",
        },
        service_factory=fallback_factory,
    )
    assert listed["count"] == 1
    assert factory_calls == [False, True]
    query = oauth.resource.calls[-1][1]
    assert query["maxResults"] == 50
    assert (
        datetime.fromisoformat(query["timeMax"])
        - datetime.fromisoformat(query["timeMin"])
    ).days == 90

    service = Service()
    created = await google_calendar.create_event(
        {
            "calendar_id": "calendar@example.test",
            "title": "Réunion",
            "start": "2026-07-27 10:00",
            "reminder_minutes": "15",
        },
        service_factory=lambda: service,
    )
    assert created["event_id"] == "new"
    body = service.resource.calls[-1][1]["body"]
    assert body["start"]["dateTime"] == "2026-07-27T10:00:00"
    assert body["end"]["dateTime"] == "2026-07-27T11:00:00"

    invalid = await google_calendar.create_event(
        {
            "calendar_id": "calendar@example.test",
            "title": "Erreur",
            "start": "2026-07-27T10:00:00",
            "end": "2026-07-27T09:00:00",
        },
        service_factory=lambda: service,
    )
    assert "error" in invalid

    confirmation = await google_calendar.delete_event(
        {"calendar_id": "calendar@example.test", "event_id": "e1"},
        service_factory=lambda: service,
    )
    assert confirmation["requiresConfirmation"] is True

    updated = await google_calendar.update_event(
        {
            "calendar_id": "calendar@example.test",
            "event_id": "e1",
            "start": "2026-07-28T14:00:00+02:00",
        },
        service_factory=lambda: service,
    )
    assert updated["success"] is True
    update_body = service.resource.calls[-1][1]["body"]
    assert update_body["end"]["dateTime"] == "2026-07-28T15:00:00+02:00"

    assert tools._google_sa_email is google_calendar.service_account_email
    assert tools._get_google_calendar_service is google_calendar.build_service
    assert tools.TOOLS_REGISTRY["calendar_list"] is tools.execute_calendar_list
    assert tools.TOOLS_REGISTRY["calendar_create"] is tools.execute_calendar_create
    assert tools.TOOLS_REGISTRY["calendar_update"] is tools.execute_calendar_update
    assert tools.TOOLS_REGISTRY["calendar_delete"] is tools.execute_calendar_delete


if __name__ == "__main__":
    asyncio.run(main())
    print("OK - domaine Google Calendar")
