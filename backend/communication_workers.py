"""Workers de communication et d'agenda de Marvin.

Les workers restent sans dependance FastAPI. Ils lisent les reglages persistants et
appellent les outils historiques; leur cycle de vie appartient au superviseur.
"""

from __future__ import annotations

import asyncio
import json
import traceback
from datetime import datetime

import database as db
import tools as tool_module


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
                    await tool_module.TOOLS_REGISTRY["email_apply_rules"]({})
                except Exception:
                    pass
                await tool_module.TOOLS_REGISTRY["email_watch_check"]({})
        except Exception:
            pass
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
                    result = await tool_module.TOOLS_REGISTRY["email_automation_run"](
                        {"source": "scheduler"}
                    )
                    last_scan = now
                    if result.get("error"):
                        print(f"[Marvin] Automatisation email : {result['error']}")
        except Exception as exc:
            try:
                import bug_log

                bug_log.log_bug(
                    "email_automation_worker",
                    str(exc),
                    traceback_str=traceback.format_exc(),
                )
            except Exception:
                pass
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
                    await tool_module.TOOLS_REGISTRY["pc_notify"](
                        {
                            "title": f"📅 Rappel : {event.get('title', 'Rendez-vous')}",
                            "message": f"À {when}{location}",
                        }
                    )
                    db.update_event(event["id"], {"reminded": True})
                except Exception:
                    pass
        except Exception:
            pass
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
                await tool_module.TOOLS_REGISTRY["calendar_sync"]({})
        except Exception:
            pass
        await asyncio.sleep(int(30 * 60 * background_scale()))
