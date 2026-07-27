"""Régressions du domaine déterministe date/heure."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from agent_safety import validator_for
from tool_domains import datetime_tools


async def run_domain() -> None:
    fixed = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    current = await datetime_tools.datetime_info(
        {"action": "now", "timezone": "Europe/Paris"},
        clock=lambda: fixed,
    )
    assert current["success"] is True
    assert current["utc"] == "2026-07-28T12:00:00+00:00"
    assert current["local"] == "2026-07-28T14:00:00+02:00"
    assert current["unix"] == 1785240000

    winter = await datetime_tools.datetime_info({
        "action": "convert",
        "timezone": "Europe/Paris",
        "datetime": "2026-01-15T12:00:00+00:00",
    })
    assert winter["converted"] == "2026-01-15T13:00:00+01:00"

    invalid_timezone = await datetime_tools.datetime_info({
        "action": "now",
        "timezone": "Europe/Does-Not-Exist",
    })
    assert "inconnu" in invalid_timezone["error"]
    assert "success" not in invalid_timezone

    difference = await datetime_tools.datetime_info({
        "action": "diff",
        "datetime": "2026-07-28T12:00:00+02:00",
        "datetime2": "2026-07-28T12:30:00+00:00",
    })
    assert difference["diff_seconds"] == 9000
    assert difference["human"] == "0j 2h 30min"

    added = await datetime_tools.datetime_info({
        "action": "add",
        "timezone": "Europe/Paris",
        "datetime": "2026-07-28T10:00:00+00:00",
        "delta": {"days": 2, "hours": 3, "minutes": 15},
    })
    assert added["result"] == "2026-07-30T15:15:00+02:00"

    unknown_delta = await datetime_tools.datetime_info({
        "action": "add",
        "datetime": "2026-07-28T10:00:00+00:00",
        "delta": {"months": 1},
    })
    assert "inconnue" in unknown_delta["error"]

    oversized = await datetime_tools.datetime_info({
        "action": "add",
        "datetime": "2026-07-28T10:00:00+00:00",
        "delta": {"days": 1_000_001},
    })
    assert "limite" in oversized["error"]


def main() -> int:
    asyncio.run(run_domain())

    import tools

    assert tools.execute_datetime_info is datetime_tools.datetime_info
    assert tools.TOOLS_REGISTRY["datetime_info"] is datetime_tools.datetime_info
    validator = validator_for(tools.TOOLS_SPEC)
    assert validator("datetime_info", {"action": "now"}) is None
    assert "months" in (
        validator(
            "datetime_info",
            {
                "action": "add",
                "datetime": "2026-07-28T10:00:00+00:00",
                "delta": {"months": 1},
            },
        )
        or ""
    )
    assert "integer" in (
        validator(
            "datetime_info",
            {
                "action": "add",
                "datetime": "2026-07-28T10:00:00+00:00",
                "delta": {"days": 1.5},
            },
        )
        or ""
    )
    print("Datetime Tools OK - IANA, DST, ISO, delta, facade et schema.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
