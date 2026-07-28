"""Contrats du domaine d'automatisation e-mail, sans réseau ni envoi."""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import email_automation


NOW = datetime(2026, 7, 28, 12, 0, 0)


def message(identifier: str, sender: str = "client@example.com") -> dict:
    return {
        "id": identifier,
        "message_id": f"<{identifier}@example.com>",
        "from": f"Client <{sender}>",
        "subject": f"Question {identifier}",
        "read": False,
        "auto_submitted": "",
        "precedence": "",
        "list_id": "",
    }


async def main() -> None:
    settings: dict = {
        "email_automation": {
            "mode": "brouillon",
            "accounts": ["a@example.com", "b@example.com"],
            "only_from": ["client@example.com"],
            "max_per_run": 2,
            "send_delay_min": 5,
            "profiles": {},
        },
        "email_auto_seen": [],
        "email_signatures": {},
    }
    writes: list[tuple[str, object]] = []
    fetched_order: list[str] = []
    sent_payloads: list[dict] = []
    accounts = [
        {"username": "a@example.com", "imap_host": "imap", "password": "x"},
        {"username": "b@example.com", "imap_host": "imap", "password": "x"},
    ]

    def get_setting(key):
        return settings.get(key)

    def set_setting(key, value):
        writes.append((key, value))
        settings[key] = value

    def fetch_inbox(_host, _port, username, _password, **_kwargs):
        return [message(f"{username[0]}1"), message(f"{username[0]}2")]

    def fetch_email(_host, _port, username, _password, *, uid, **kwargs):
        fetched_order.append(f"{username}:{uid}:{kwargs['mark_seen']}")
        return {
            "body": "Merci de me répondre.",
            "reply_to": "client@example.com",
            "message_id": f"<{uid}@example.com>",
            "references": "",
        }

    async def draft_reply(args):
        return {
            "draft": "Réponse professionnelle suffisamment longue.",
            "to": "client@example.com",
            "subject": f"Re: {args['subject']}",
        }

    async def send_email(args):
        sent_payloads.append(args)
        return {"success": True}

    email_automation.configure(
        get_setting=get_setting,
        set_setting=set_setting,
        list_accounts=lambda: accounts,
        fetch_inbox=fetch_inbox,
        fetch_email=fetch_email,
        draft_reply=draft_reply,
        send_email=send_email,
        clock=lambda: NOW,
    )

    dry_run = await email_automation.run({"dry_run": True, "source": "test"})
    assert dry_run["success"] and dry_run["processed"] == 4
    assert fetched_order == [
        "a@example.com:a1:False",
        "b@example.com:b1:False",
        "a@example.com:a2:False",
        "b@example.com:b2:False",
    ]
    assert writes == [] and sent_payloads == []

    settings["email_automation"]["mode"] = "differe"
    queued = await email_automation.run({"source": "test"})
    assert queued["queued"] == 4 and queued["drafted"] == 0
    outbox = settings["email_scheduled_outbox"]
    assert len(outbox) == 4
    assert all(item["send_after"] == "2026-07-28T12:05:00" for item in outbox)
    assert len(settings["email_auto_seen"]) == 4
    assert settings["email_automation_runs"][-1]["queued"] == 4

    settings["email_scheduled_outbox"] = [
        {**outbox[0], "send_after": (NOW - timedelta(minutes=1)).isoformat()},
        {**outbox[1], "send_after": (NOW + timedelta(minutes=1)).isoformat()},
    ]
    flushed = await email_automation.flush_outbox()
    assert flushed == {"success": True, "sent": 1, "failed": 0, "pending": 1}
    assert len(sent_payloads) == 1 and sent_payloads[0]["confirmed"] is True

    async def failed_send(_args):
        return {"success": False, "error": "SMTP indisponible"}

    email_automation.configure(
        get_setting=get_setting,
        set_setting=set_setting,
        list_accounts=lambda: accounts,
        fetch_inbox=fetch_inbox,
        fetch_email=fetch_email,
        draft_reply=draft_reply,
        send_email=failed_send,
        clock=lambda: NOW,
    )
    settings["email_scheduled_outbox"] = [
        {**outbox[0], "send_after": (NOW - timedelta(minutes=1)).isoformat()},
    ]
    failed = await email_automation.flush_outbox()
    assert failed["failed"] == 1 and failed["pending"] == 1
    assert settings["email_scheduled_outbox"][0]["send_after"] == "2026-07-28T12:05:00"
    assert settings["email_scheduled_outbox"][0]["last_error"] == "SMTP indisponible"

    def slow_inbox(*args, **kwargs):
        time.sleep(0.15)
        return fetch_inbox(*args, **kwargs)

    settings["email_automation"]["mode"] = "brouillon"
    settings["email_auto_seen"] = []
    email_automation.configure(
        get_setting=get_setting,
        set_setting=set_setting,
        list_accounts=lambda: accounts,
        fetch_inbox=slow_inbox,
        fetch_email=fetch_email,
        draft_reply=draft_reply,
        send_email=send_email,
        clock=lambda: NOW,
    )
    running = asyncio.create_task(email_automation.run({"dry_run": True}))
    await asyncio.sleep(0.02)
    concurrent = await email_automation.run({"dry_run": True})
    assert "déjà en cours" in concurrent["error"]
    await running

    settings["email_automation"]["mode"] = "autonome"
    settings["email_automation"]["only_from"] = []
    blocked = await email_automation.run({"dry_run": True})
    assert all(item["action"] == "ignoré" for item in blocked["results"])
    assert all("liste d'expéditeurs" in item["reason"] for item in blocked["results"])

    assert tools.execute_email_orchestrator_run is email_automation.run
    assert tools.execute_email_outbox_flush is email_automation.flush_outbox
    assert tools.TOOLS_REGISTRY["email_automation_run"] is email_automation.run
    print("Email Automation Domain OK - équité, simulation, file, retry, verrou et façade.")


if __name__ == "__main__":
    asyncio.run(main())
