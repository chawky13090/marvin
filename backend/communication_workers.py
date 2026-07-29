"""Workers de communication et d'agenda de Marvin.

Les workers restent sans dependance FastAPI. Ils lisent les reglages persistants et
appellent les outils historiques; leur cycle de vie appartient au superviseur.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime

import bug_log
import database as db
import tool_runtime
import tools as tool_module


_last_worker_errors: dict[str, tuple[str, float]] = {}


def _report_worker_failure(component: str, error: Exception) -> None:
    signature = type(error).__name__
    now = time.monotonic()
    previous_signature, previous_at = _last_worker_errors.get(component, ("", 0.0))
    if signature == previous_signature and now - previous_at < 300:
        return
    _last_worker_errors[component] = (signature, now)
    try:
        bug_log.log_bug(
            component,
            "Worker de communication indisponible.",
            context={"exception_type": signature},
        )
    except Exception:
        pass


async def _worker_tool(
    name: str,
    arguments: dict,
    *,
    source: str,
    request_id: str | None = None,
):
    return await tool_runtime.execute(
        name,
        arguments,
        source=source,
        conversation_id=f"worker:{source}",
        request_id=request_id,
    )


async def email_watch_worker() -> None:
    await asyncio.sleep(30)
    while True:
        interval = 5
        try:
            config = db.get_setting("email_watch")
            if isinstance(config, str):
                try:
                    config = json.loads(config)
                except Exception:
                    config = {}
            config = config if isinstance(config, dict) else {}
            interval = max(2, int(config.get("interval_min", 5)))
            if config.get("enabled"):
                try:
                    await _worker_tool(
                        "email_apply_rules", {}, source="email_watch_worker"
                    )
                except Exception as exc:
                    _report_worker_failure("email_rules_worker", exc)
                await _worker_tool(
                    "email_watch_check", {}, source="email_watch_worker"
                )
        except Exception as exc:
            _report_worker_failure("email_watch_worker", exc)
        await asyncio.sleep(interval * 60)


async def email_automation_worker() -> None:
    await asyncio.sleep(30)
    last_scan = 0.0
    while True:
        try:
            config = tool_module._email_automation_cfg()
            if config.get("scheduler_enabled"):
                await tool_module.execute_email_outbox_flush()
                now = asyncio.get_running_loop().time()
                interval_seconds = max(2, int(config.get("interval_min", 5))) * 60
                if not last_scan or now - last_scan >= interval_seconds:
                    cycle = datetime.now().strftime("%Y%m%d%H%M")
                    outcome = await _worker_tool(
                        "email_automation_run",
                        {"source": "scheduler"},
                        source="email_automation_worker",
                        request_id=f"email-automation:{cycle}",
                    )
                    result = outcome.result
                    last_scan = now
                    if result.get("error"):
                        print(f"[Marvin] Automatisation email : {result['error']}")
        except Exception as exc:
            _report_worker_failure("email_automation_worker", exc)
        await asyncio.sleep(30)


async def event_reminder_worker() -> None:
    await asyncio.sleep(20)
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            for event in db.events_needing_reminder(now):
                try:
                    when = (event.get("start_at") or "")[11:16] or "aujourd'hui"
                    location = f" ({event['location']})" if event.get("location") else ""
                    outcome = await _worker_tool(
                        "pc_notify",
                        {
                            "title": f"📅 Rappel : {event.get('title', 'Rendez-vous')}",
                            "message": f"À {when}{location}",
                        },
                        source="event_reminder_worker",
                        request_id=f"event-reminder:{event['id']}",
                    )
                    if outcome.executed and not (
                        isinstance(outcome.result, dict) and outcome.result.get("error")
                    ):
                        db.update_event(event["id"], {"reminded": True})
                except Exception as exc:
                    _report_worker_failure("event_reminder_worker", exc)
        except Exception as exc:
            _report_worker_failure("event_reminder_worker", exc)
        await asyncio.sleep(60)


def background_scale() -> float:
    try:
        return max(0.25, float(db.get_setting("bg_scale") or 1.0))
    except Exception:
        return 1.0


async def calendar_sync_worker() -> None:
    await asyncio.sleep(15)
    while True:
        try:
            subscriptions = db.get_setting("calendar_subscriptions")
            google_ready = tool_module._google_calendar_ready()
            if subscriptions or google_ready:
                await _worker_tool(
                    "calendar_sync", {}, source="calendar_sync_worker"
                )
        except Exception as exc:
            _report_worker_failure("calendar_sync_worker", exc)
        await asyncio.sleep(int(30 * 60 * background_scale()))
