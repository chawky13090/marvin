"""Live smoke test for allowlisted official engineering documentation."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import engineering_radar


async def exercise(languages: list[str]) -> None:
    result = await engineering_radar.refresh(languages, force=True)
    if result["errors"]:
        raise RuntimeError(f"Actualisation échouée : {result['errors']}")
    radar = engineering_radar.context(languages)
    assert radar["available"] is True
    expected = sum(
        item["language"] in set(languages) for item in engineering_radar.SOURCES
    )
    assert radar["source_count"] == expected
    assert all(item["freshness"] == "current" for item in radar["sources"])
    assert all(len(str(item["content_sha256"])) == 64 for item in radar["sources"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("languages", nargs="*", default=["go"])
    arguments = parser.parse_args()
    asyncio.run(exercise(arguments.languages))
    print(
        "Engineering Knowledge Radar LIVE OK - documentation officielle téléchargée "
        f"et vérifiée pour {', '.join(arguments.languages)}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
