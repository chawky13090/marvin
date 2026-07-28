"""Contrats Telegram sans message externe ni secret réel."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import telegram


VALID_TOKEN = "123456789:" + "A" * 35


@dataclass
class FakeResponse:
    status_code: int
    text: str = ""


async def main() -> None:
    settings: dict = {}
    calls: list[dict] = []

    def get_setting(key: str):
        return settings.get(key)

    async def post(url: str, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse(200)

    telegram.configure(get_setting=get_setting, post=post)
    assert telegram.get_config() == {}
    assert telegram.public_config() == {
        "enabled": False,
        "chat_id": "",
        "has_token": False,
    }
    missing = await telegram.execute_send({"text": "Bonjour"})
    assert "non configuré" in missing["error"]
    assert calls == []

    settings["telegram_config"] = "{malformed"
    assert telegram.get_config() == {}
    settings["telegram_config"] = {
        "enabled": True,
        "bot_token": "bad/token",
        "chat_id": "1",
    }
    invalid = await telegram.send("Bonjour")
    assert "jeton" in invalid["error"]
    assert calls == []

    settings["telegram_config"] = {
        "enabled": True,
        "bot_token": VALID_TOKEN,
        "chat_id": "-123456",
    }
    sent = await telegram.execute_send({"text": "<b>Bonjour</b>"})
    assert sent["success"] is True
    assert calls[-1]["json"]["text"] == "&lt;b&gt;Bonjour&lt;/b&gt;"
    assert VALID_TOKEN not in repr(sent)

    rich = await telegram.notify("<b>Alerte</b>")
    assert rich["success"] is True
    assert calls[-1]["json"]["text"] == "<b>Alerte</b>"
    settings["telegram_config"]["enabled"] = False
    skipped = await telegram.notify("Alerte")
    assert skipped == {"success": False, "skipped": True, "reason": "disabled"}

    async def failed_post(_url: str, **_kwargs):
        raise RuntimeError(f"secret URL contains {VALID_TOKEN}")

    settings["telegram_config"]["enabled"] = True
    telegram.configure(get_setting=get_setting, post=failed_post)
    failure = await telegram.send("Alerte")
    assert failure["error_type"] == "RuntimeError"
    assert VALID_TOKEN not in repr(failure)

    async def rejected_post(_url: str, **_kwargs):
        return FakeResponse(429, f"secret={VALID_TOKEN}")

    telegram.configure(get_setting=get_setting, post=rejected_post)
    rejected = await telegram.send("Alerte")
    assert rejected["status_code"] == 429
    assert VALID_TOKEN not in repr(rejected)

    telegram.configure(get_setting=get_setting, post=post)
    assert tools._telegram_cfg is telegram.get_config
    assert tools._send_telegram is telegram.send
    assert tools._telegram_notify is telegram.notify
    assert tools.execute_telegram_send is telegram.execute_send
    assert tools.TOOLS_REGISTRY["telegram_send"] is telegram.execute_send
    print(
        "Telegram Domain OK - configuration, validation, HTML, secret, "
        "panne, notification et façades."
    )


if __name__ == "__main__":
    asyncio.run(main())
