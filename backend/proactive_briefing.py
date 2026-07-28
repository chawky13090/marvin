"""Construction injectable et observable du briefing quotidien de Marvin."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any


FRENCH_WEEKDAYS = (
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
)
FRENCH_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)

Generate = Callable[..., Awaitable[str]]
NetworkError = Callable[[Exception, str], dict[str, Any]]

_list_tasks: Callable[..., list[dict[str, Any]]] | None = None
_list_events: Callable[..., list[dict[str, Any]]] | None = None
_list_accounts: Callable[[], list[dict[str, Any]]] | None = None
_fetch_inbox: Callable[..., list[dict[str, Any]]] | None = None
_generate: Generate | None = None
_network_error: NetworkError | None = None
_today: Callable[[], date] = date.today


def configure(
    *,
    list_tasks: Callable[..., list[dict[str, Any]]],
    list_events: Callable[..., list[dict[str, Any]]],
    list_accounts: Callable[[], list[dict[str, Any]]],
    fetch_inbox: Callable[..., list[dict[str, Any]]],
    generate: Generate,
    network_error: NetworkError,
    today: Callable[[], date] = date.today,
) -> None:
    global _list_tasks, _list_events, _list_accounts, _fetch_inbox
    global _generate, _network_error, _today
    _list_tasks = list_tasks
    _list_events = list_events
    _list_accounts = list_accounts
    _fetch_inbox = fetch_inbox
    _generate = generate
    _network_error = network_error
    _today = today


def _require_dependencies() -> None:
    if any(
        dependency is None
        for dependency in (
            _list_tasks,
            _list_events,
            _list_accounts,
            _fetch_inbox,
            _generate,
            _network_error,
        )
    ):
        raise RuntimeError("Le briefing proactif n'est pas configuré.")


def _text(value: Any, maximum: int) -> str:
    return str(value or "").strip()[:maximum]


def _valid_records(value: Any, maximum: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [record for record in value[:maximum] if isinstance(record, dict)]


def _today_label(current: date) -> str:
    return (
        f"{FRENCH_WEEKDAYS[current.weekday()]} {current.day} "
        f"{FRENCH_MONTHS[current.month - 1]} {current.year}"
    )


async def _safe_storage_call(
    name: str,
    function: Callable[..., Any],
    /,
    *args: Any,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = asyncio.get_running_loop().time()
    try:
        result = await asyncio.to_thread(function, *args, **kwargs)
        records = _valid_records(result, 100)
        return records, {
            "source": name,
            "status": "ok",
            "count": len(records),
            "duration_ms": round((asyncio.get_running_loop().time() - started) * 1_000),
        }
    except Exception as error:
        return [], {
            "source": name,
            "status": "error",
            "count": 0,
            "error": str(error),
            "duration_ms": round((asyncio.get_running_loop().time() - started) * 1_000),
        }


async def _unread_emails() -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    assert _list_accounts and _fetch_inbox
    try:
        accounts = _valid_records(await asyncio.to_thread(_list_accounts), 50)
    except Exception as error:
        return [], [
            {
                "source": "email_accounts",
                "status": "error",
                "count": 0,
                "error": str(error),
            }
        ]
    semaphore = asyncio.Semaphore(4)

    async def fetch(account: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
        username = _text(account.get("username"), 320)
        if not username or not account.get("imap_host") or not account.get("password"):
            return [], {
                "source": f"email:{username or '?'}",
                "status": "invalid",
                "count": 0,
                "error": "Configuration de compte incomplète.",
            }
        started = asyncio.get_running_loop().time()
        try:
            async with semaphore:
                messages = await asyncio.to_thread(
                    _fetch_inbox,
                    account["imap_host"],
                    int(account.get("imap_port", 993)),
                    username,
                    account["password"],
                    folder="INBOX",
                    limit=12,
                    offset=0,
                )
            unread = [
                {
                    "from": _text(message.get("from"), 2_000),
                    "subject": _text(message.get("subject"), 998),
                    "account": username,
                }
                for message in _valid_records(messages, 12)
                if not message.get("read")
            ]
            return unread, {
                "source": f"email:{username}",
                "status": "ok",
                "count": len(unread),
                "duration_ms": round(
                    (asyncio.get_running_loop().time() - started) * 1_000
                ),
            }
        except Exception as error:
            return [], {
                "source": f"email:{username}",
                "status": "error",
                "count": 0,
                "error": str(error),
                "duration_ms": round(
                    (asyncio.get_running_loop().time() - started) * 1_000
                ),
            }

    batches = await asyncio.gather(*(fetch(account) for account in accounts))
    unread = [message for messages, _status in batches for message in messages]
    statuses = [status for _messages, status in batches]
    return unread[:200], statuses


def _event_time(event: dict[str, Any]) -> str:
    start = _text(event.get("start_at") or event.get("start"), 100)
    return start[11:16] if len(start) >= 16 else "journée"


async def build(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    assert _list_tasks and _list_events and _generate and _network_error
    current = _today()
    label = _today_label(current)
    start = current.strftime("%Y-%m-%d 00:00")
    end = current.strftime("%Y-%m-%d 23:59")

    task_job = asyncio.create_task(
        _safe_storage_call("tasks", _list_tasks, limit=50)
    )
    event_job = asyncio.create_task(
        _safe_storage_call("events", _list_events, start=start, end=end, limit=30)
    )
    email_job = asyncio.create_task(_unread_emails())
    (all_tasks, task_status), (events, event_status), (
        unread,
        email_statuses,
    ) = await asyncio.gather(task_job, event_job, email_job)

    pending = [
        task
        for task in all_tasks
        if _text(task.get("status"), 30).casefold()
        not in {"done", "completed", "cancelled", "canceled"}
    ]
    task_lines = (
        "\n".join(
            f"- [{_text(task.get('priority') or 'medium', 20)}] "
            f"{_text(task.get('title'), 300)}"
            + (
                f" (échéance {_text(task.get('due_date'), 32)})"
                if task.get("due_date")
                else ""
            )
            for task in pending[:15]
        )
        or "(aucune)"
    )
    mail_lines = (
        "\n".join(
            f"- De {message['from']} : {message['subject']}" for message in unread[:20]
        )
        or "(aucun)"
    )
    event_lines = (
        "\n".join(
            f"- {_event_time(event)} : {_text(event.get('title'), 300)}"
            + (
                f" @ {_text(event.get('location'), 500)}"
                if event.get("location")
                else ""
            )
            for event in events[:30]
        )
        or "(aucun)"
    )
    prompt = (
        "Tu es l'assistant personnel de l'utilisateur. Rédige son BRIEFING DU JOUR en "
        f"français, chaleureux mais concis et actionnable. Nous sommes le {label}.\n\n"
        f"RENDEZ-VOUS DU JOUR ({len(events)}) :\n{event_lines}\n\n"
        f"TÂCHES EN ATTENTE ({len(pending)}) :\n{task_lines}\n\n"
        f"EMAILS NON LUS ({len(unread)}) :\n{mail_lines}\n\n"
        "Structure ta réponse :\n"
        "1) Une salutation courte adaptée au moment.\n"
        "2) 📅 AGENDA : rappelle les rendez-vous du jour dans l'ordre (s'il y en a).\n"
        "3) 🔴 PRIORITÉS DU JOUR : les mails vraiment importants à traiter + les tâches "
        "urgentes (ignore pubs/newsletters/notifs).\n"
        "4) 🟡 À VOIR : ce qui peut attendre.\n"
        "5) Une phrase de motivation finale.\n"
        "Sois synthétique, va à l'essentiel."
    )
    try:
        briefing = _text(
            await _generate(prompt, model=args.get("model"), timeout=180),
            100_000,
        )
    except Exception as error:
        return _network_error(error, "briefing du jour")
    if not briefing:
        return {"error": "L'IA n'a pas produit de briefing. Réessayez."}

    source_status = [task_status, event_status, *email_statuses]
    errors = [
        {
            "source": status["source"],
            "error": status.get("error", "Source indisponible."),
        }
        for status in source_status
        if status["status"] != "ok"
    ]
    urgent = [
        task
        for task in pending
        if _text(task.get("priority"), 20).casefold() == "high"
    ]
    return {
        "success": True,
        "briefing": briefing,
        "date": label,
        "tasks_pending": len(pending),
        "tasks_urgent": len(urgent),
        "unread": len(unread),
        "tasks": pending[:15],
        "events_today": events[:30],
        "source_status": source_status,
        "errors": errors,
        "partial": bool(errors),
        "message": "Briefing du jour généré.",
    }
