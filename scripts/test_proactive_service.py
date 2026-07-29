"""Regressions du service proactif sans notification ni synthese externes."""

from __future__ import annotations

import ast
import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import proactive_service


EXPECTED_IMPORTS = {"_proactive_worker": "proactive_worker"}


def _check_main_facade() -> None:
    tree = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8-sig"))
    imports: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "proactive_service":
            imports.update({item.asname or item.name: item.name for item in node.names})
    assert imports == EXPECTED_IMPORTS
    definitions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not set(EXPECTED_IMPORTS).intersection(definitions)
    assert {
        "daily_briefing",
        "get_proactive",
        "set_proactive",
        "run_proactive_now",
    }.isdisjoint(definitions)
    source = (BACKEND / "main.py").read_text(encoding="utf-8-sig")
    assert "from api.proactive import router as proactive_router" in source
    assert "app.include_router(proactive_router)" in source


def _check_defaults_and_quiet_hours() -> None:
    config = proactive_service.with_defaults({})
    assert set(config) == {"morning_briefing", "evening_recap", "anticipation", "quiet_hours"}
    assert config["morning_briefing"]["enabled"] is False
    overnight = {"quiet_hours": {"enabled": True, "start": "22:00", "end": "07:00"}}
    assert proactive_service.in_quiet_hours(overnight, "23:30") is True
    assert proactive_service.in_quiet_hours(overnight, "06:59") is True
    assert proactive_service.in_quiet_hours(overnight, "12:00") is False
    malformed = proactive_service.with_defaults(
        {
            "morning_briefing": "invalid",
            "evening_recap": {"enabled": "yes", "time": "25:90", "voice_name": "../voice"},
            "anticipation": {
                "interval_min": -10,
                "upcoming_events_min": 100_000,
                "max_notify": 0,
            },
            "quiet_hours": None,
            "unknown": {"kept": False},
        }
    )
    assert malformed["morning_briefing"]["time"] == "08:00"
    assert malformed["evening_recap"]["enabled"] is False
    assert malformed["evening_recap"]["time"] == "18:30"
    assert malformed["evening_recap"]["voice_name"] == "henri"
    assert malformed["anticipation"]["interval_min"] == 5
    assert malformed["anticipation"]["upcoming_events_min"] == 1440
    assert malformed["anticipation"]["max_notify"] == 1
    assert "unknown" not in malformed


async def _check_tts_voice_contract() -> None:
    observed: dict[str, str] = {}

    class Communication:
        def __init__(self, text: str, voice: str) -> None:
            observed.update(text=text, voice=voice)

        async def stream(self):
            yield {"type": "audio", "data": b"first"}
            yield {"type": "metadata", "data": b"ignored"}
            yield {"type": "audio", "data": b"second"}

    fake_edge_tts = types.SimpleNamespace(Communicate=Communication)
    with patch.dict(sys.modules, {"edge_tts": fake_edge_tts}):
        audio = await proactive_service.tts_bytes("**Bonjour**", "denise")
    assert audio == b"firstsecond"
    assert observed == {"text": "Bonjour", "voice": "fr-FR-DeniseNeural"}


async def _check_morning_briefing() -> None:
    async def run_tool(name, _arguments, *, source):
        assert source == "proactive_morning"
        if name == "daily_briefing":
            return {
            "success": True,
            "events_today": [{"id": "evt"}],
            "tasks_urgent": 2,
            "unread": 3,
            "briefing": "Votre journee est chargee.",
            }
        if name == "pc_notify":
            await notify()
            return {"success": True}
        raise AssertionError(name)

    notify = AsyncMock(return_value={"success": True})
    telegram = AsyncMock(return_value={"success": True})
    speak = AsyncMock()
    with (
        patch.object(proactive_service, "_run_tool", side_effect=run_tool),
        patch.object(proactive_service.tool_module, "_telegram_notify", telegram),
        patch.object(proactive_service, "speak_backend", speak),
    ):
        result = await proactive_service.run_morning_briefing(
            {"voice": True, "voice_name": "denise"}
        )
    assert result == {
        "success": True,
        "summary": "Aujourd'hui : 1 rendez-vous, 2 tâche(s) urgente(s), 3 mail(s) non lus.",
    }
    speak.assert_awaited_once_with("Bonjour ! Votre journee est chargee.", "denise")
    notify.assert_awaited_once()
    telegram.assert_awaited_once()


def main() -> int:
    _check_main_facade()
    _check_defaults_and_quiet_hours()
    asyncio.run(_check_tts_voice_contract())
    asyncio.run(_check_morning_briefing())
    print("Proactive Service OK - facade, heures calmes, voix et briefing sans effet externe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
