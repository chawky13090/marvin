"""Deterministic durable coding mission regressions."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import coding_mission


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        original = coding_mission.ROOT
        coding_mission.ROOT = Path(temporary) / "coding_missions"
        try:
            mission = coding_mission.create("Construire un service avancé", target_platforms=["windows", "linux"])
            mission = coding_mission.checkpoint(
                mission["id"], "architected", expected_revision=0,
                state={"components": 3, "api_token": "must-not-leak"},
            )
            assert mission["history"][-1]["state"]["api_token"] == "***"
            files = {
                "main.go": "package main\nfunc main() {}\n",
                "go.mod": "module example.com/sample\n\ngo 1.26\n",
            }
            mission = coding_mission.checkpoint(
                mission["id"], "testing", expected_revision=1, files=files,
            )
            assert coding_mission.latest_files(mission["id"]) == files
            assert coding_mission.latest_manifest(mission["id"])[0]["sha256"]
            assert coding_mission.list_missions()[0]["id"] == mission["id"]
            assert coding_mission.list_missions(status="failed") == []
            assert coding_mission.list_events(mission["id"])[0]["type"] == "checkpoint"
            context = coding_mission.resume_context(mission["id"])
            assert context["revision"] == 2 and context["files"]["main.go"].startswith("package")
            try:
                coding_mission.checkpoint(mission["id"], "reviewing", expected_revision=1)
            except coding_mission.MissionConflict:
                pass
            else:
                raise AssertionError("Une écriture concurrente périmée doit être refusée.")
            completed = coding_mission.checkpoint(mission["id"], "accepted", expected_revision=2)
            assert completed["status"] == "completed"
            assert coding_mission.list_missions(status="completed")[0]["id"] == mission["id"]
            events = (coding_mission.ROOT / mission["id"] / "events.jsonl").read_text(encoding="utf-8")
            assert len([line for line in events.splitlines() if json.loads(line)]) == 4
        finally:
            coding_mission.ROOT = original
    print("Advanced Coding Mission OK - snapshots, reprise, redaction et concurrence optimiste.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
