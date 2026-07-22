"""Régressions de la frontière IMAP/SMTP multi-comptes."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from api import email_mailbox


CONFIG = {
    "imap_host": "imap.example.test",
    "imap_port": 993,
    "smtp_host": "smtp.example.test",
    "smtp_port": 587,
    "username": "user@example.test",
    "password": "secret",
}


async def _run() -> None:
    with (
        patch.object(email_mailbox.accounts, "list_resolved", return_value=[CONFIG]),
        patch.object(
            email_mailbox.email_manager,
            "fetch_inbox",
            return_value=[{"uid": "1", "date": "2026-07-22"}],
        ),
    ):
        inbox = await email_mailbox.email_inbox(account="__all__", limit=5)
    assert inbox["unified"] is True
    assert inbox["emails"][0]["_account"] == CONFIG["username"]

    request = email_mailbox.SendEmailRequest(to="a@example.test", subject="Sujet", body="Texte")
    with (
        patch.object(email_mailbox.accounts, "get_resolved", return_value=CONFIG),
        patch.object(email_mailbox.email_manager, "send_email", return_value={"success": True}) as send,
        patch.object(email_mailbox.db, "log_execution") as log,
    ):
        result = await email_mailbox.email_send(request)
    assert result["success"] is True
    assert send.call_args.kwargs["to"] == "a@example.test"
    log.assert_called_once_with(
        "email_send", {"to": "a@example.test", "subject": "Sujet"}, {"success": True}, 0
    )

    with (
        patch.object(email_mailbox.accounts, "get_resolved", return_value=CONFIG),
        patch.object(
            email_mailbox.email_manager,
            "fetch_attachment",
            return_value={"name": "rapport été.pdf", "data": b"PDF", "content_type": "application/pdf"},
        ),
    ):
        response = await email_mailbox.email_attachment("1")
    assert response.body == b"PDF"
    assert "rapport%20%C3%A9t%C3%A9.pdf" in response.headers["content-disposition"]

    with patch.object(email_mailbox.accounts, "get_resolved", return_value=None):
        try:
            await email_mailbox.email_send(request)
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("Un envoi sans compte doit être refusé")


def main() -> int:
    asyncio.run(_run())
    import main as application

    expected = {
        ("/api/email/inbox", "GET"),
        ("/api/email/read/{uid}", "GET"),
        ("/api/email/search", "GET"),
        ("/api/email/folders", "GET"),
        ("/api/email/send", "POST"),
        ("/api/email/{uid}", "DELETE"),
        ("/api/email/mark", "POST"),
        ("/api/email/move", "POST"),
        ("/api/email/attachment", "GET"),
    }
    observed: set[tuple[str, str]] = set()
    for route in application.app.routes:
        path = getattr(route, "path", "")
        endpoint = getattr(route, "endpoint", None)
        for method in getattr(route, "methods", set()):
            pair = (path, method)
            if pair in expected:
                assert endpoint.__module__ == "api.email_mailbox", pair
                observed.add(pair)
    assert observed == expected, sorted(expected - observed)
    print("Email Mailbox Boundary OK - multi-boîtes, envoi, audit, pièce jointe et 9 routes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
