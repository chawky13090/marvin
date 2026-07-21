"""Régressions déterministes Evolution Lab, Mission Canvas et jobs Swarm."""
from __future__ import annotations
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import evolution_lab
import mission_os
import swarm_jobs

def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        with (
            patch.object(evolution_lab, "PATH", Path(tmp) / "evo.json"),
            patch.object(evolution_lab.db, "get_setting", return_value=3),
            patch.object(evolution_lab.db, "set_setting") as setter,
        ):
            exp = evolution_lab.create("Concurrence", "research_swarm_concurrency", 4, "Améliorer le débit")
            evaluated = evolution_lab.evaluate(exp["id"],
                [{"success": True, "duration_ms": 100} for _ in range(3)],
                [{"success": True, "duration_ms": 90} for _ in range(3)])
            assert not evaluated["evaluation"]["promotable"]
            better = evolution_lab.evaluate(exp["id"],
                [{"success": i < 2, "duration_ms": 100} for i in range(3)],
                [{"success": True, "duration_ms": 105} for _ in range(3)])
            assert better["evaluation"]["promotable"]
            evolution_lab.promote(exp["id"], True); setter.assert_called()
        with (
            patch.object(mission_os, "MISSIONS_PATH", Path(tmp) / "missions.json"),
            patch.object(mission_os, "EVENTS_PATH", Path(tmp) / "events.jsonl"),
            patch.object(mission_os.db if hasattr(mission_os, "db") else mission_os, "dummy", create=True),
        ):
            mission = mission_os.create_mission(goal="Test", conversation_id="c", tag="t", steps=["A"], task_ids=["1"])
            assert mission_os.pause_mission(mission["id"])["status"] == "paused"
            assert mission_os.resume_mission(mission["id"])["status"] == "running"
    assert swarm_jobs.JOBS_PATH.name == "research_swarm_jobs.json"
    print("Evolution Lab et Mission Canvas OK - promotion bornée, pause/reprise et jobs persistants.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
