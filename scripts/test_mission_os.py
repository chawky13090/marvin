"""Régressions Mission OS et Proof-Carrying Actions, sans LLM ni base réelle."""
from __future__ import annotations

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
            events = mission_os.list_events(mission_id=mission["id"])
            action = next(item for item in events if item["type"] == "action_proof")
            assert action["payload"]["arguments"]["token"] == "***"

            mission_os.checkpoint(mission["id"], "Etat stable", {"path": "C:/test"})
            completed = mission_os.sync_steps(
                mission["id"],
                [{"id": 1, "status": "done"}, {"id": 2, "status": "done"}],
            )
            assert completed["status"] == "completed"
            assert len(completed["checkpoints"]) == 1

            rollback = mission_os.rollback_hint("email_send")
            assert rollback is None
        finally:
            mission_os.MISSIONS_PATH = original_missions
            mission_os.EVENTS_PATH = original_events

    print("Mission OS OK - état durable, checkpoints, preuves expurgées et terminaison.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
