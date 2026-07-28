"""Contrats de surveillance et classement e-mail, sans réseau ni mutation réelle."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import email_monitoring


ACCOUNTS = [
    {
        "username": "a@example.test",
        "imap_host": "imap.example.test",
        "imap_port": 993,
        "password": "credential-a",
    },
    {
        "username": "b@example.test",
        "imap_host": "imap.example.test",
        "imap_port": 993,
        "password": "credential-b",
    },
]


async def main() -> None:
    settings: dict = {
        "email_watch": {
            "enabled": True,
            "accounts": [],
            "max_notify": 2,
        },
        "email_watch_seen": [],
        "email_watch_alerts": [],
        "email_rules": [],
    }
    writes: list[tuple[str, object]] = []
    desktop_notifications: list[dict] = []
    telegram_notifications: list[str] = []
    moved: list[dict] = []
    marked: list[dict] = []
    inbox_calls: list[dict] = []
    generated_prompts: list[str] = []

    def get_setting(key):
        return settings.get(key)

    def set_setting(key, value):
        settings[key] = value
        writes.append((key, value))

    def fetch_inbox(_host, _port, username, _password, **kwargs):
        inbox_calls.append({"username": username, **kwargs})
        prefix = username[0]
        return [
            {
                "id": f"{prefix}{index}",
                "from": f"Client {index} <client{index}@example.test>",
                "subject": f"Question {index}",
                "read": False,
            }
            for index in range(1, 12)
        ]

    def move_email(_host, _port, username, _password, **kwargs):
        moved.append({"username": username, **kwargs})

    def mark_email(_host, _port, username, _password, **kwargs):
        marked.append({"username": username, **kwargs})

    async def generate(prompt, **_kwargs):
        generated_prompts.append(prompt)
        return '{"important":[1,20]}'

    async def desktop_notify(args):
        desktop_notifications.append(args)
        return {"success": True}

    async def telegram_notify(text):
        telegram_notifications.append(text)
        return {"success": True}

    def configure(*, generator=generate, inbox=fetch_inbox):
        email_monitoring.configure(
            get_setting=get_setting,
            set_setting=set_setting,
            list_accounts=lambda: ACCOUNTS,
            fetch_inbox=inbox,
            move_email=move_email,
            mark_email=mark_email,
            generate=generator,
            desktop_notify=desktop_notify,
            telegram_notify=telegram_notify,
            clock=lambda: datetime(2026, 7, 28, 12, 30, 0),
        )

    configure()

    watched = await email_monitoring.watch_check({})
    assert watched["success"] and watched["checked"] == 22
    assert watched["classified"] == 22 and watched["important"] == 2
    assert len(generated_prompts) == 2
    assert len(desktop_notifications) == 2 and len(telegram_notifications) == 2
    assert len(settings["email_watch_seen"]) == 22
    assert settings["email_watch_alerts"][0]["at"] == "2026-07-28T12:30:00"

    settings["email_watch_seen"] = []
    settings["email_watch_alerts"] = []
    desktop_notifications.clear()
    telegram_notifications.clear()
    dry_run = await email_monitoring.watch_check({"dry_run": True})
    assert dry_run["dry_run"] and dry_run["important"] == 2
    assert desktop_notifications == [] and telegram_notifications == []
    assert len(settings["email_watch_seen"]) == 22

    async def invalid_generation(_prompt, **_kwargs):
        return "réponse non structurée"

    settings["email_watch_seen"] = []
    settings["email_watch_alerts"] = []
    configure(generator=invalid_generation)
    unclassified = await email_monitoring.watch_check({})
    assert unclassified["classified"] == 0 and unclassified["important"] == 0
    assert len(unclassified["errors"]) == 2
    assert settings["email_watch_seen"] == []

    async def slow_generation(prompt, **kwargs):
        await asyncio.sleep(0.1)
        return await generate(prompt, **kwargs)

    configure(generator=slow_generation)
    settings["email_watch_seen"] = []
    running = asyncio.create_task(email_monitoring.watch_check({}))
    await asyncio.sleep(0.01)
    concurrent = await email_monitoring.watch_check({})
    assert "déjà en cours" in concurrent["error"]
    await running

    no_rules = await email_monitoring.apply_rules({"dry_run": True})
    assert no_rules["applied"] == 0 and no_rules["dry_run"] is True

    settings["email_rules"] = [
        "invalide",
        {
            "name": "Action inconnue",
            "from_contains": "client",
            "action": "delete",
        },
        {
            "name": "Déplacer client",
            "from_contains": "client 1 <",
            "action": "move",
            "folder": "Clients",
        },
        {
            "name": "Marquer question",
            "subject_contains": "question 2",
            "action": "mark_read",
            "account": "b@example.test",
        },
    ]
    moved.clear()
    marked.clear()
    simulated = await email_monitoring.apply_rules({"dry_run": True, "limit": 999})
    assert simulated["success"] and simulated["applied"] == 3
    assert moved == [] and marked == []
    assert inbox_calls[-1]["limit"] == 100
    assert any("Action inconnue" in item.get("error", "") for item in simulated["results"])

    applied = await email_monitoring.apply_rules({"limit": "invalide"})
    assert applied["applied"] == 3
    assert len(moved) == 2 and len(marked) == 1
    assert all(call["dest_folder"] == "Clients" for call in moved)
    assert all(call["seen"] is True for call in marked)

    def failing_inbox(*_args, **_kwargs):
        raise OSError("IMAP indisponible")

    configure(inbox=failing_inbox)
    failed = await email_monitoring.apply_rules({})
    assert failed["applied"] == 0
    assert len([item for item in failed["results"] if item.get("action") == "erreur"]) == 2

    assert tools.execute_email_watch_check is email_monitoring.watch_check
    assert tools.execute_email_apply_rules is email_monitoring.apply_rules
    assert tools.TOOLS_REGISTRY["email_watch_check"] is email_monitoring.watch_check
    assert tools.TOOLS_REGISTRY["email_apply_rules"] is email_monitoring.apply_rules
    tools_source = (BACKEND / "tools.py").read_text(encoding="utf-8")
    assert "async def execute_email_watch_check" not in tools_source
    assert "async def execute_email_apply_rules" not in tools_source
    assert "def _email_rules" not in tools_source

    print(
        "Email Monitoring Domain OK - lots IA, reprises, notifications, "
        "règles, simulation, bornes, concurrence et façades."
    )


if __name__ == "__main__":
    asyncio.run(main())
