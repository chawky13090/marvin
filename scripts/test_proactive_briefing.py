"""Contrats du briefing proactif, sans base, réseau ni LLM réels."""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import proactive_briefing
import tools


ACCOUNTS = [
    {
        "username": "a@example.test",
        "imap_host": "imap.example.test",
        "password": "credential-a",
    },
    {
        "username": "b@example.test",
        "imap_host": "imap.example.test",
        "password": "credential-b",
    },
]


async def main() -> None:
    prompts: list[str] = []
    calls: list[str] = []

    def list_tasks(**kwargs):
        calls.append(f"tasks:{kwargs['limit']}")
        time.sleep(0.08)
        return [
            {"id": "1", "title": "Traiter incident", "priority": "high", "status": "pending"},
            {"id": "2", "title": "Terminé", "priority": "high", "status": "done"},
            {"id": "3", "title": "Annulé", "priority": "low", "status": "cancelled"},
            {"id": "4", "title": "Préparer devis", "priority": "medium", "status": "pending"},
        ]

    def list_events(**kwargs):
        calls.append(f"events:{kwargs['start']}:{kwargs['end']}:{kwargs['limit']}")
        time.sleep(0.08)
        return [
            {
                "id": "e1",
                "title": "Intervention",
                "start_at": "2026-07-28 09:30:00",
                "location": "KOIOS",
            }
        ]

    def fetch_inbox(_host, _port, username, _password, **kwargs):
        calls.append(f"email:{username}:{kwargs['limit']}")
        time.sleep(0.08)
        return [
            {
                "id": "m1",
                "from": "Client <client@example.test>",
                "subject": f"Question {username}",
                "read": False,
            },
            {"id": "m2", "from": "Robot", "subject": "Déjà lu", "read": True},
        ]

    async def generate(prompt, **_kwargs):
        prompts.append(prompt)
        return "Briefing validé"

    def network_error(error, resource):
        return {"error": f"{resource}: {error}"}

    def configure(
        *,
        tasks=list_tasks,
        events=list_events,
        inbox=fetch_inbox,
        generator=generate,
    ):
        proactive_briefing.configure(
            list_tasks=tasks,
            list_events=events,
            list_accounts=lambda: ACCOUNTS,
            fetch_inbox=inbox,
            generate=generator,
            network_error=network_error,
            today=lambda: date(2026, 7, 28),
        )

    configure()
    started = time.perf_counter()
    result = await proactive_briefing.build({})
    elapsed = time.perf_counter() - started
    assert result["success"] and result["briefing"] == "Briefing validé"
    assert result["date"] == "mardi 28 juillet 2026"
    assert result["tasks_pending"] == 2 and result["tasks_urgent"] == 1
    assert result["unread"] == 2 and len(result["events_today"]) == 1
    assert result["partial"] is False and result["errors"] == []
    assert len(result["source_status"]) == 4
    assert elapsed < 0.25, f"Les sources ne semblent pas concurrentes : {elapsed:.3f}s"
    assert "09:30 : Intervention @ KOIOS" in prompts[-1]
    assert "Traiter incident" in prompts[-1] and "Question a@example.test" in prompts[-1]
    assert "Terminé" not in prompts[-1] and "Annulé" not in prompts[-1]

    def partial_inbox(*args, **kwargs):
        if args[2] == "b@example.test":
            raise OSError("IMAP indisponible")
        return fetch_inbox(*args, **kwargs)

    configure(inbox=partial_inbox)
    partial = await proactive_briefing.build({})
    assert partial["success"] and partial["partial"]
    assert partial["unread"] == 1
    assert partial["errors"] == [
        {"source": "email:b@example.test", "error": "IMAP indisponible"}
    ]

    def failed_tasks(**_kwargs):
        raise RuntimeError("SQLite indisponible")

    configure(tasks=failed_tasks)
    storage_failure = await proactive_briefing.build({})
    assert storage_failure["success"] and storage_failure["partial"]
    assert storage_failure["tasks_pending"] == 0
    assert any(error["source"] == "tasks" for error in storage_failure["errors"])

    async def empty_generation(_prompt, **_kwargs):
        return ""

    configure(generator=empty_generation)
    empty = await proactive_briefing.build({})
    assert "n'a pas produit" in empty["error"]

    async def failed_generation(_prompt, **_kwargs):
        raise TimeoutError("modèle indisponible")

    configure(generator=failed_generation)
    failed = await proactive_briefing.build({})
    assert failed == {"error": "briefing du jour: modèle indisponible"}

    assert tools.execute_daily_briefing is proactive_briefing.build
    assert tools.TOOLS_REGISTRY["daily_briefing"] is proactive_briefing.build
    tools_source = (BACKEND / "tools.py").read_text(encoding="utf-8")
    assert "async def execute_daily_briefing" not in tools_source
    print(
        "Proactive Briefing OK - sources concurrentes, filtrage, provenance, "
        "pannes partielles, génération et façade."
    )


if __name__ == "__main__":
    asyncio.run(main())
