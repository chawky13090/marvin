"""Gate structurel de l'inventaire contractuel FastAPI."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api_contract_inventory import inventory
from app_version import APP_VERSION
from main import app


DOCUMENT = ROOT / "MARVIN-API-CONTRACT.md"


def _baseline(text: str) -> dict[str, int]:
    match = re.search(r"<!-- api-contract-baseline\s*(.*?)\s*-->", text, re.DOTALL)
    if not match:
        raise AssertionError("Baseline api-contract absente.")
    result: dict[str, int] = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        key, value = [part.strip() for part in line.split("|", 1)]
        result[key] = int(value)
    return result


def main() -> int:
    report = inventory(app.openapi())
    assert report["version"] == APP_VERSION
    assert report["openapi"].startswith("3.")
    assert not report["duplicate_operations"]
    assert not report["duplicate_operation_ids"]
    assert report["missing_operation_ids"] == 0
    baseline = _baseline(DOCUMENT.read_text(encoding="utf-8-sig"))
    for key, value in baseline.items():
        assert report[key] == value, (
            f"Baseline API désynchronisée pour {key}: {report[key]} != {value}"
        )
    assert sum(row["operations"] for row in report["families"].values()) == report["operations"]
    print(
        "API Contract Inventory OK - "
        f"{report['operations']} opérations, {len(report['families'])} familles, "
        f"{report['documented_errors']} erreurs explicites, "
        f"{report['secured']} opérations sécurisées."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
