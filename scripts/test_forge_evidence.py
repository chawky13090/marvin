"""Vérifie la conservation et l'intégrité des exécutions Marvin Forge."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import forge  # noqa: E402


def run() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        previous = (forge.SCENARIOS_PATH, forge.RUNS_PATH)
        try:
            forge.SCENARIOS_PATH = root / "scenarios.json"
            forge.RUNS_PATH = root / "runs.jsonl"
            forge._RUNS_STORE = None
            forge._RUNS_STORE_PATH = None
            forge.save_scenario(
                {
                    "id": "evidence-test",
                    "name": "Preuve durable",
                    "prompt": "Répondre OK",
                    "expectations": {
                        "require_done": True,
                        "forbid_all_tools": True,
                        "contains_all": ["OK"],
                    },
                }
            )
            legacy = {
                "id": "legacy-run",
                "scenario_id": "evidence-test",
                "scenario_name": "Preuve durable",
                "created_at": "2026-01-01T00:00:00Z",
                "success": True,
                "score": 1.0,
            }
            forge.RUNS_PATH.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
            run = forge.record_run(
                "evidence-test",
                [{"type": "text", "content": "OK"}, {"type": "done"}],
                duration_ms=10,
            )
            assert run["success"] is True
            assert run["sequence"] == 2
            assert len(run["record_hash"]) == 64
            rows = forge.list_runs(limit=10, scenario_id="evidence-test")
            assert [row["id"] for row in rows] == [run["id"], "legacy-run"]
            summary = forge.summary()
            assert summary["runs"] == 2
            assert summary["integrity"]["valid"] is True
            assert summary["integrity"]["legacy_records"] == 1
            assert summary["integrity"]["signed_records"] == 1
            assert summary["integrity"]["retention"] == "owner_lifecycle"
        finally:
            forge.SCENARIOS_PATH, forge.RUNS_PATH = previous
            forge._RUNS_STORE = None
            forge._RUNS_STORE_PATH = None

    print("Forge Evidence OK - preuves conservées, chaînées, lisibles et vérifiables.")


if __name__ == "__main__":
    run()
