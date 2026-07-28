"""Régressions des graphiques PNG bornés et atomiques."""

from __future__ import annotations

import asyncio
import math
import sys
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tools
from tool_domains import charts


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-charts-") as temporary:
        root = Path(temporary)
        charts.configure(
            resolve_path=lambda raw: str((root / raw).resolve()),
            default_output=lambda: root / "default.png",
        )
        labels = ["A", "B", "C"]
        values = [2, 5, 3]
        series = [
            {"name": "2025", "values": [1, 3, 2]},
            {"name": "2026", "values": [2, 4, 5]},
        ]
        cases = {
            "bar": {"values": values},
            "horizontal_bar": {"values": [-2, 5, 3]},
            "pie": {"values": values},
            "donut": {"values": values},
            "line": {"values": values},
            "area": {"values": values},
            "multi_line": {"series": series},
            "scatter": {"values": values, "x_values": [10, 20, 30]},
            "radar": {"series": series},
            "grouped_bar": {"series": series},
            "stacked_bar": {"series": series},
        }
        for chart_type, payload in cases.items():
            result = await charts.create(
                {
                    "chart_type": chart_type,
                    "title": f"Test {chart_type}",
                    "labels": labels,
                    "output_path": f"{chart_type}.png",
                    **payload,
                }
            )
            assert result["success"] is True, result
            output = Path(result["path"])
            assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            with Image.open(output) as image:
                image.verify()
            assert not list(root.glob(".*.tmp.png"))

        assert "exactement 3" in (
            await charts.create(
                {"title": "x", "labels": labels, "values": [1, 2]}
            )
        )["error"]
        assert "non finie" in (
            await charts.create(
                {"title": "x", "labels": labels, "values": [1, math.inf, 2]}
            )
        )["error"]
        assert "valeurs négatives" in (
            await charts.create(
                {
                    "chart_type": "pie",
                    "title": "x",
                    "labels": labels,
                    "values": [1, -1, 2],
                }
            )
        )["error"]
        assert "au moins trois" in (
            await charts.create(
                {
                    "chart_type": "radar",
                    "title": "x",
                    "labels": ["A", "B"],
                    "values": [1, 2],
                }
            )
        )["error"]
        assert "exige 'series'" in (
            await charts.create(
                {
                    "chart_type": "grouped_bar",
                    "title": "x",
                    "labels": labels,
                    "values": values,
                }
            )
        )["error"]
        invalid_color = await charts.create(
            {
                "title": "x",
                "labels": labels,
                "values": values,
                "colors": ["not-a-color"],
            }
        )
        assert "couleur" in invalid_color["error"].lower()

    charts.configure(
        resolve_path=tools._resolve_path,
        default_output=lambda: (
            Path(tools._SYSTEM_PATHS["desktop"])
            / "infographie_test.png"
        ),
    )
    assert tools.execute_infographic_create is charts.create
    assert tools.TOOLS_REGISTRY["infographic_create"] is charts.create


if __name__ == "__main__":
    asyncio.run(main())
    print("Charts OK - 11 types PNG, validation, atomicité et façade.")
