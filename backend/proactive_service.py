"""Service proactif de Marvin : briefings, anticipation et lecture locale."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import database as db
import tools as tool_module
from api.voice import DEFAULT_TTS_VOICES


_anticipation_seen: dict[str, Any] = {"date": None, "ids": set()}
_last_briefing_date: dict[str, str | None] = {"date": None}
_last_recap_date: dict[str, str | None] = {"date": None}


def get_config() -> dict[str, Any]:
    config = db.get_setting("proactive_config")
    if isinstance(config, str):
        import json

        try:
            config = json.loads(config)
        except Exception:
            config = {}
    return config if isinstance(config, dict) else {}


def with_defaults(config: dict[str, Any]) -> dict[str, Any]:
    config.setdefault(
        "morning_briefing",
        {"enabled": False, "time": "08:00", "voice": False, "voice_name": "henri"},
    )
    config.setdefault(
        "evening_recap",
        {"enabled": False, "time": "18:30", "voice": False, "voice_name": "henri"},
    )
    config.setdefault(
        "anticipation",
        {
            "enabled": False,
            "interval_min": 30,
            "overdue_tasks": True,
            "upcoming_events": True,
            "upcoming_events_min": 30,
            "max_notify": 5,
        },
    )
    config.setdefault("quiet_hours", {"enabled": False, "start": "22:00", "end": "07:00"})
    return config


def in_quiet_hours(config: dict[str, Any], current_hm: str) -> bool:
    quiet = config.get("quiet_hours", {})
    if not quiet.get("enabled"):
        return False
    start = quiet.get("start", "22:00")
    end = quiet.get("end", "07:00")
    if start <= end:
        return start <= current_hm < end
    return current_hm >= start or current_hm < end


async def tts_bytes(text: str, voice: str = "henri") -> bytes:
    import edge_tts

    voice_id = DEFAULT_TTS_VOICES.get(voice, {}).get("id", "fr-FR-HenriNeural")
    normalized = re.sub(r"[*#`_>]+", "", text or "").strip()
    if not normalized:
        return b""
    communication = edge_tts.Communicate(normalized[:1500], voice_id)
    chunks: list[bytes] = []
    async for chunk in communication.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


def play_mp3_bytes_sync(mp3: bytes) -> None:
    """Convertit le MP3 dans un dossier temporaire prive puis le joue sous Windows."""
    try:
        import imageio_ffmpeg
        import winsound
    except Exception:
        return
    try:
        with tempfile.TemporaryDirectory(prefix="marvin-voice-") as temporary:
            root = Path(temporary)
            mp3_path = root / "speech.mp3"
            wav_path = root / "speech.wav"
            mp3_path.write_bytes(mp3)
            completed = subprocess.run(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(),
                    "-y",
                    "-i",
                    os.fspath(mp3_path),
                    "-ar",
                    "22050",
                    "-ac",
                    "1",
                    os.fspath(wav_path),
                ],
                capture_output=True,
                creationflags=0x08000000,
                timeout=60,
                check=False,
            )
            if completed.returncode == 0 and wav_path.exists():
                winsound.PlaySound(os.fspath(wav_path), winsound.SND_FILENAME)
    except Exception:
        pass


async def speak_backend(text: str, voice: str = "henri") -> None:
    try:
        mp3 = await tts_bytes(text, voice)
        if mp3:
            await asyncio.get_running_loop().run_in_executor(None, play_mp3_bytes_sync, mp3)
    except Exception:
        pass


async def run_morning_briefing(config: dict[str, Any]) -> dict[str, Any]:
    result = await tool_module.TOOLS_REGISTRY["daily_briefing"]({})
    if not result.get("success"):
        return {"error": result.get("error", "briefing indisponible")}
    events = result.get("events_today") or []
    parts = [f"{len(events)} rendez-vous" if events else "aucun rendez-vous"]
    if result.get("tasks_urgent"):
        parts.append(f"{result['tasks_urgent']} tâche(s) urgente(s)")
    elif result.get("tasks_pending"):
        parts.append(f"{result['tasks_pending']} tâche(s)")
    if result.get("unread"):
        parts.append(f"{result['unread']} mail(s) non lus")
    summary = "Aujourd'hui : " + ", ".join(parts) + "."
    try:
        await tool_module.TOOLS_REGISTRY["pc_notify"](
            {"title": "🌅 Votre briefing du jour", "message": summary}
        )
    except Exception:
        pass
    try:
        await tool_module._telegram_notify("🌅 <b>Briefing du jour</b>\n" + summary)
    except Exception:
        pass
    if config.get("voice"):
        await speak_backend(
            "Bonjour ! " + (result.get("briefing") or summary),
            config.get("voice_name", "henri"),
        )
    return {"success": True, "summary": summary}


async def run_evening_recap(config: dict[str, Any]) -> dict[str, Any]:
    registry = tool_module.TOOLS_REGISTRY
    result = await registry["daily_briefing"]({})
    try:
        tomorrow = await registry["event_list"]({"period": "tomorrow"})
        tomorrow_events = tomorrow.get("events") or []
    except Exception:
        tomorrow_events = []
    parts: list[str] = []
    if result.get("tasks_urgent"):
        parts.append(f"{result['tasks_urgent']} tâche(s) urgente(s) en attente")
    elif result.get("tasks_pending"):
        parts.append(f"{result['tasks_pending']} tâche(s) en attente")
    parts.append(f"{len(tomorrow_events)} RDV demain" if tomorrow_events else "rien de prévu demain")
    if result.get("unread"):
        parts.append(f"{result['unread']} mail(s) non lus")
    summary = "Bilan du soir — " + ", ".join(parts) + "."
    try:
        await registry["pc_notify"]({"title": "🌙 Bilan du soir", "message": summary})
    except Exception:
        pass
    try:
        await tool_module._telegram_notify("🌙 <b>Bilan du soir</b>\n" + summary)
    except Exception:
        pass
    if config.get("voice"):
        await speak_backend("Bonsoir ! " + summary, config.get("voice_name", "henri"))
    return {"success": True, "summary": summary}


async def run_anticipation(config: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    registry = tool_module.TOOLS_REGISTRY
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    if _anticipation_seen["date"] != today:
        _anticipation_seen["date"] = today
        _anticipation_seen["ids"] = set()
    seen = _anticipation_seen["ids"]
    alerts: list[dict[str, str]] = []

    if config.get("overdue_tasks", True):
        try:
            tasks = await registry["task_list"]({})
            for task in tasks.get("tasks") or []:
                due = (task.get("due_date") or "")[:10]
                if due and due < today and task.get("status") not in {"done", "completed", "cancelled"}:
                    key = "ovd_" + str(task.get("id"))
                    if force or key not in seen:
                        seen.add(key)
                        alerts.append(
                            {
                                "type": "task_overdue",
                                "key": key,
                                "text": f"⏰ En retard : « {task.get('title', 'tâche')} » (échéance {due})",
                            }
                        )
        except Exception:
            pass

    if config.get("upcoming_events", True):
        lead = int(config.get("upcoming_events_min", 30))
        try:
            events = await registry["event_list"]({"period": "today"})
            for event in events.get("events") or []:
                raw = event.get("start_at") or event.get("start") or ""
                try:
                    from dateutil import parser as date_parser

                    start = date_parser.parse(raw)
                    if start.tzinfo:
                        start = start.replace(tzinfo=None)
                    minutes = (start - now).total_seconds() / 60
                except Exception:
                    continue
                if 0 <= minutes <= lead:
                    key = "evt_" + str(event.get("id") or raw)
                    if force or key not in seen:
                        seen.add(key)
                        alerts.append(
                            {
                                "type": "event_soon",
                                "key": key,
                                "text": f"📅 Dans {int(minutes)} min : {event.get('title') or event.get('summary', 'RDV')}",
                            }
                        )
        except Exception:
            pass

    maximum = int(config.get("max_notify", 5))
    selected = alerts[:maximum]
    for alert in selected:
        try:
            await registry["pc_notify"]({"title": "🔔 Marvin anticipe", "message": alert["text"]})
        except Exception:
            pass
        try:
            await tool_module._telegram_notify("🔔 " + alert["text"])
        except Exception:
            pass
    if selected:
        try:
            import audit

            audit.log_action(
                "anticipation_notify",
                {"alertes": len(selected)},
                {"message": "; ".join(alert["text"] for alert in selected)[:200]},
                source="proactif",
            )
        except Exception:
            pass
    return {"success": True, "alerts": alerts, "count": len(alerts)}


async def proactive_worker() -> None:
    await asyncio.sleep(25)
    last_anticipation = 0.0
    while True:
        try:
            config = get_config()
            now = datetime.now()
            current_hm = now.strftime("%H:%M")
            day = now.strftime("%Y-%m-%d")
            quiet = in_quiet_hours(config, current_hm)
            morning = config.get("morning_briefing", {})
            if (
                morning.get("enabled")
                and current_hm == morning.get("time", "08:00")
                and _last_briefing_date["date"] != day
            ):
                _last_briefing_date["date"] = day
                if not quiet:
                    await run_morning_briefing(morning)
            evening = config.get("evening_recap", {})
            if (
                evening.get("enabled")
                and current_hm == evening.get("time", "18:30")
                and _last_recap_date["date"] != day
            ):
                _last_recap_date["date"] = day
                if not quiet:
                    await run_evening_recap(evening)
            anticipation = config.get("anticipation", {})
            if anticipation.get("enabled") and not quiet:
                interval = max(5, int(anticipation.get("interval_min", 30))) * 60
                if time.time() - last_anticipation >= interval:
                    last_anticipation = time.time()
                    await run_anticipation(anticipation)
        except Exception:
            pass
        await asyncio.sleep(30)
