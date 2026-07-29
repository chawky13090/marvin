"""Contrat du canal d'activité éphémère des outils."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tool_activity


async def main() -> int:
    received: list[dict] = []
    with tool_activity.bind(received.append):
        await tool_activity.emit(
            "searching",
            "  Recherche   réelle  ",
            detail="x" * 500,
            current=12,
            total=4,
            metrics={"sources": 18, "invalid": "non numérique"},
        )
    assert len(received) == 1
    event = received[0]
    assert event["label"] == "Recherche réelle"
    assert event["current"] == 4
    assert event["total"] == 4
    assert len(event["detail"]) == 240
    assert event["metrics"] == {"sources": 18}

    await tool_activity.emit("searching", "Sans récepteur")
    print("Tool Activity OK - bornes, typage, contexte et absence de persistance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
