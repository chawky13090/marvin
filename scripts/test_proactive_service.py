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


EXPECTED_IMPORTS = {
    "_get_proactive_cfg": "get_config",
    "_in_quiet_hours": "in_quiet_hours",
    "_proactive_worker": "proactive_worker",
    "run_anticipation": "run_anticipation",
    "run_evening_recap": "run_evening_recap",
    "run_morning_briefing": "run_morning_briefing",
    "_proactive_with_defaults": "with_defaults",
}


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


def _check_defaults_and_quiet_hours() -> None:
    config = proactive_service.with_defaults({})
    assert set(config) == {"morning_briefing", "evening_recap", "anticipation", "quiet_hours"}
    assert config["morning_briefing"]["enabled"] is False
    overnight = {"quiet_hours": {"enabled": True, "start": "22:00", "end": "07:00"}}
    assert proactive_service.in_quiet_hours(overnight, "23:30") is True
    assert proactive_service.in_quiet_hours(overnight, "06:59") is True
    assert proactive_service.in_quiet_hours(overnight, "12:00") is False


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
    briefing = AsyncMock(
        return_value={
            "success": True,
            "events_today": [{"id": "evt"}],
            "tasks_urgent": 2,
            "unread": 3,
            "briefing": "Votre journee est chargee.",
        }
    )
    notify = AsyncMock(return_value={"success": True})
    telegram = AsyncMock(return_value={"success": True})
    speak = AsyncMock()
    with (
        patch.dict(
            proactive_service.tool_module.TOOLS_REGISTRY,
            {"daily_briefing": briefing, "pc_notify": notify},
        ),
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
