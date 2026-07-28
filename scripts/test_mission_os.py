"""Régressions Mission OS et Proof-Carrying Actions, sans LLM ni base réelle."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import mission_os


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        original_missions = mission_os.MISSIONS_PATH
        original_events = mission_os.EVENTS_PATH
        try:
            mission_os.MISSIONS_PATH = root / "missions.json"
            mission_os.EVENTS_PATH = root / "events.jsonl"
            mission_os._EVENT_STORE = None
            mission_os._EVENT_STORE_PATH = None
            mission_os.EVENTS_PATH.write_text(
                json.dumps(
                    {
                        "id": "legacy-event",
                        "at": "2026-01-01T00:00:00Z",
                        "type": "legacy",
                        "mission_id": None,
                        "payload": {},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            mission = mission_os.create_mission(
                goal="Valider une mission",
                conversation_id="conv-test",
                tag="longtask:test",
                steps=["Etape 1", "Etape 2"],
                task_ids=[1, 2],
            )
            assert mission["status"] == "running"
            assert mission_os.find_active(conversation_id="conv-test")["id"] == mission["id"]

            proof = mission_os.record_action(
                conversation_id="conv-test",
                tool_name="pc_run_powershell",
                arguments={"command": "Get-Date", "token": "secret-value"},
                result={"success": True, "stdout": "ok"},
                duration_ms=42,
            )
            assert proof["verified"] is True
            assert proof["evidence_sequence"] == 3
            assert len(proof["evidence_hash"]) == 64
            events = mission_os.list_events(mission_id=mission["id"])
            action = next(item for item in events if item["type"] == "action_proof")
            assert action["payload"]["arguments"]["token"] == "***"
            assert action["record_hash"] == proof["evidence_hash"]

            mission_os.checkpoint(mission["id"], "Etat stable", {"path": "C:/test"})
            completed = mission_os.sync_steps(
                mission["id"],
                [{"id": 1, "status": "done"}, {"id": 2, "status": "done"}],
            )
            assert completed["status"] == "completed"
            assert len(completed["checkpoints"]) == 1
            assert mission_os.list_events(mission_id=mission["id"])[0]["type"] == "mission_completed"
            integrity = mission_os.evidence_integrity()
            assert integrity["valid"] is True
            assert integrity["legacy_records"] == 1
            assert integrity["signed_records"] == 4
            assert integrity["retention"] == "owner_lifecycle"

            rollback = mission_os.rollback_hint("email_send")
            assert rollback is None

            before = mission_os.get_mission(mission["id"])
            with mission_os.EVENTS_PATH.open("a", encoding="utf-8") as stream:
                stream.write("not-json\n")
            try:
                mission_os.checkpoint(mission["id"], "Ne doit pas rester", {})
            except RuntimeError:
                pass
            else:
                raise AssertionError("Une preuve corrompue doit bloquer la mutation.")
            after = mission_os.get_mission(mission["id"])
            assert after == before
            assert mission_os.evidence_integrity()["valid"] is False
        finally:
            mission_os.MISSIONS_PATH = original_missions
            mission_os.EVENTS_PATH = original_events
            mission_os._EVENT_STORE = None
            mission_os._EVENT_STORE_PATH = None

    print("Mission OS OK - état durable, checkpoints, preuves expurgées et terminaison.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
