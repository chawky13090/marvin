"""Régressions de la frontière IA et automatisation e-mail."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from api import email_automation


async def _run() -> None:
    body = email_automation.AutomationConfig(scheduler_enabled=True)
    with patch.object(email_automation.db, "get_setting", return_value={}):
        try:
            await email_automation.set_email_automation(body)
        except HTTPException as exc:
            assert exc.status_code == 409 and "Confirmation explicite" in exc.detail
        else:
            raise AssertionError("L'activation initiale doit exiger une confirmation")

    confirmed = email_automation.AutomationConfig(
        scheduler_enabled=True,
        scheduler_confirmed=True,
        interval_min=1,
        max_per_run=500,
        send_delay_min=0,
        accounts=["a@example.test", "b@example.test"],
    )
    with (
        patch.object(email_automation.db, "get_setting", return_value={}),
        patch.object(email_automation.db, "set_setting") as save,
    ):
        result = await email_automation.set_email_automation(confirmed)
    assert result["scheduler_enabled"] is True
    stored = save.call_args.args[1]
    assert stored["interval_min"] == 2 and stored["max_per_run"] == 100
    assert stored["send_delay_min"] == 1 and "scheduler_confirmed" not in stored
    assert stored["accounts"] == ["a@example.test", "b@example.test"]

    gateway_calls = []

    async def execute(name, arguments, **options):
        gateway_calls.append((name, arguments, options))
        result = (
            {"success": True, "draft": "Bonjour"}
            if name == "email_draft_reply"
            else {"success": True, "processed": 0}
        )
        return SimpleNamespace(result=result, status_code=200)
    request = email_automation.DraftReplyRequest(
        uid="42", **{"from": "sender@example.test"}, instruction="Réponds brièvement"
    )
    with patch.object(email_automation.tool_runtime, "execute", side_effect=execute):
        await email_automation.email_draft_reply(request)
        await email_automation.run_email_automation(dry_run=True, mode="autonome")
    assert gateway_calls[0][1]["from"] == "sender@example.test"
    assert gateway_calls[0][2] == {
        "source": "email_ui",
        "confirmed_by_ui": False,
    }
    assert gateway_calls[1][1] == {
        "dry_run": True,
        "mode": "autonome",
        "source": "manual",
    }
    assert gateway_calls[1][2]["confirmed_by_ui"] is False

    outbox = [{"id": "keep"}, {"id": "cancel"}]
    with (
        patch.object(email_automation.db, "get_setting", return_value=outbox),
        patch.object(email_automation.db, "set_setting") as save,
    ):
        cancelled = await email_automation.cancel_email_automation_outbox("cancel")
    assert cancelled == {"success": True, "cancelled": "cancel"}
    save.assert_called_once_with("email_scheduled_outbox", [{"id": "keep"}])


def main() -> int:
    asyncio.run(_run())
    import main as application

    expected = {
        ("/api/email/draft-reply", "POST"), ("/api/email/summarize", "POST"),
        ("/api/email/digest", "GET"), ("/api/email/automation", "GET"),
        ("/api/email/automation", "POST"), ("/api/email/automation/run", "POST"),
        ("/api/email/automation/status", "GET"),
        ("/api/email/automation/drafts", "GET"),
        ("/api/email/automation/drafts/clear", "POST"),
        ("/api/email/automation/outbox", "GET"),
        ("/api/email/automation/outbox/{item_id}", "DELETE"),
        ("/api/email/to-task", "POST"), ("/api/email/attachment/summary", "GET"),
    }
    observed: set[tuple[str, str]] = set()
    for route in application.app.routes:
        endpoint = getattr(route, "endpoint", None)
        for method in getattr(route, "methods", set()):
            pair = (getattr(route, "path", ""), method)
            if pair in expected:
                assert endpoint.__module__ == "api.email_automation", pair
                observed.add(pair)
    assert observed == expected, sorted(expected - observed)
    print("Email Automation Boundary OK - confirmation, bornes, outils, outbox et 13 routes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
