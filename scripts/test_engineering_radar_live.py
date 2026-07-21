"""Live smoke test for allowlisted official engineering documentation."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import engineering_radar


async def exercise() -> None:
    result = await engineering_radar.refresh(["go"], force=True)
    if result["errors"]:
        raise RuntimeError(f"Actualisation Go échouée : {result['errors']}")
    radar = engineering_radar.context(["go"])
    assert radar["available"] is True
    assert radar["source_count"] == 2
    assert all(item["freshness"] == "current" for item in radar["sources"])
    assert all(len(str(item["content_sha256"])) == 64 for item in radar["sources"])


def main() -> int:
    asyncio.run(exercise())
    print("Engineering Knowledge Radar LIVE OK - documentation Go officielle téléchargée et vérifiée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
