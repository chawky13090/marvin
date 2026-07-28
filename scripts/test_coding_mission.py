"""Deterministic durable coding mission regressions."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import coding_mission


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        original = coding_mission.ROOT
        coding_mission.ROOT = Path(temporary) / "coding_missions"
        try:
            for invalid_id in ("", "a" * 31, "g" * 32, "../" + "a" * 29):
                try:
                    coding_mission.get(invalid_id)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Un identifiant de mission invalide doit être refusé.")
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
            newest = coding_mission.list_events(mission["id"])[0]
            assert newest["type"] == "checkpoint"
            assert newest["sequence"] == 3 and len(newest["record_hash"]) == 64
            first_page = coding_mission.stream_events(mission["id"], after=0, limit=2)
            assert [event["cursor"] for event in first_page["events"]] == [1, 2]
            second_page = coding_mission.stream_events(
                mission["id"], after=first_page["cursor"], limit=2
            )
            assert second_page["events"][0]["cursor"] == 3
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
            integrity = coding_mission.evidence_integrity(mission["id"])
            assert integrity["valid"] is True
            assert integrity["integrity_level"] == "tamper_evident"
            assert integrity["signed_records"] == 4
            assert integrity["retention"] == "owner_lifecycle"

            mission_path = coding_mission.ROOT / mission["id"] / "mission.json"
            before = mission_path.read_bytes()
            with (coding_mission.ROOT / mission["id"] / "events.jsonl").open(
                "a", encoding="utf-8", newline="\n"
            ) as stream:
                stream.write("corruption-complete\n")
            try:
                coding_mission.checkpoint(
                    mission["id"],
                    "testing",
                    expected_revision=3,
                    files={"main.go": "package main\n// nouvelle revision\n"},
                )
            except RuntimeError:
                pass
            else:
                raise AssertionError("Une preuve corrompue doit bloquer le checkpoint.")
            assert mission_path.read_bytes() == before
            assert not (
                coding_mission.ROOT / mission["id"] / "snapshots" / "snapshot-0004.json"
            ).exists()
            assert coding_mission.evidence_integrity(mission["id"])["valid"] is False

            existing = {path.name for path in coding_mission.ROOT.iterdir()}
            with patch.object(
                coding_mission.DurableEvidenceStore,
                "append",
                side_effect=RuntimeError("preuve indisponible"),
            ):
                try:
                    coding_mission.create("Mission à annuler")
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("La création sans preuve doit échouer.")
            assert {path.name for path in coding_mission.ROOT.iterdir()} == existing
        finally:
            coding_mission.ROOT = original
    print("Advanced Coding Mission OK - snapshots, reprise, redaction et concurrence optimiste.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
