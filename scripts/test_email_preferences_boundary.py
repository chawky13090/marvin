"""Régressions de la frontière des préférences et règles e-mail."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from api import email_preferences


async def _run() -> None:
    assert email_preferences.coerce_object('{"a": 1}', {}) == {"a": 1}
    assert email_preferences.coerce_object("JSON invalide", {}) == {}

    with (
        patch.object(email_preferences.db, "get_setting", return_value={}),
        patch.object(email_preferences.db, "set_setting") as save,
    ):
        result = await email_preferences.set_signatures({
            "account": " user@example.test ", "signature": "Cordialement"
        })
    assert result["success"] is True
    save.assert_called_once_with(
        "email_signatures", {"user@example.test": "Cordialement"}
    )

    existing = [{"name": "Réponse", "body": "Ancien"}]
    with (
        patch.object(email_preferences.db, "get_setting", return_value=existing),
        patch.object(email_preferences.db, "set_setting") as save,
    ):
        result = await email_preferences.add_template({"name": "Réponse", "body": "Nouveau"})
    assert result["count"] == 1
    save.assert_called_once_with("email_templates", [{"name": "Réponse", "body": "Nouveau"}])

    calls = []

    async def execute(name, arguments, **options):
        calls.append((name, arguments, options))
        return SimpleNamespace(result={"success": True})

    with patch.object(email_preferences.tool_runtime, "execute", side_effect=execute):
        await email_preferences.run_email_watch()
        await email_preferences.run_email_rules(dry_run=True, account="user@example.test")
    assert calls == [
        ("email_watch_check", {"force": True}, {"source": "email_ui"}),
        (
            "email_apply_rules",
            {"dry_run": True, "account": "user@example.test"},
            {"source": "email_ui"},
        ),
    ]


def main() -> int:
    asyncio.run(_run())
    import main as application

    expected = {
        ("/api/email/signatures", "GET"), ("/api/email/signatures", "POST"),
        ("/api/email/templates", "GET"), ("/api/email/templates", "POST"),
        ("/api/email/templates/{name}", "DELETE"),
        ("/api/email/watch", "GET"), ("/api/email/watch", "POST"),
        ("/api/email/watch/run", "POST"), ("/api/email/watch/alerts", "GET"),
        ("/api/email/watch/alerts/clear", "POST"),
        ("/api/email/rules", "GET"), ("/api/email/rules", "POST"),
        ("/api/email/rules/run", "POST"),
    }
    observed: set[tuple[str, str]] = set()
    for route in application.app.routes:
        endpoint = getattr(route, "endpoint", None)
        for method in getattr(route, "methods", set()):
            pair = (getattr(route, "path", ""), method)
            if pair in expected:
                assert endpoint.__module__ == "api.email_preferences", pair
                observed.add(pair)
    assert observed == expected, sorted(expected - observed)
    print("Email Preferences Boundary OK - signatures, modèles, surveillance, règles et 13 routes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
