"""Régressions des tâches longues, y compris compensation d'une écriture partielle."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import database
import mission_os
import tools
from tool_domains import long_tasks


class FakeDatabase:
    def __init__(self, *, fail_cron: bool = False) -> None:
        self.fail_cron = fail_cron
        self.tasks: list[dict[str, Any]] = []
        self.jobs: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    def create_task(self, **kwargs: Any) -> dict[str, Any]:
        task = {
            "id": f"task-{len(self.tasks) + 1}",
            "title": kwargs["title"],
            "status": "pending",
            "tags": kwargs["tags"],
        }
        self.tasks.append(task)
        return task

    def delete_task(self, task_id: str) -> None:
        self.deleted.append(task_id)
        self.tasks = [task for task in self.tasks if task["id"] != task_id]

    def list_tasks(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return list(self.tasks)

    def create_cron_job(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail_cron:
            raise RuntimeError("cron indisponible")
        job = {"id": "job-1", "enabled": True, **kwargs}
        self.jobs.append(job)
        return job

    def list_cron_jobs(self) -> list[dict[str, Any]]:
        return list(self.jobs)

    def update_cron_job(
        self, job_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        for job in self.jobs:
            if job["id"] == job_id:
                job.update(updates)
                return job
        return None


class FakeMissions:
    def __init__(self) -> None:
        self.missions: list[dict[str, Any]] = []

    def create_mission(self, **kwargs: Any) -> dict[str, Any]:
        mission = {"id": "mission-1", **kwargs}
        self.missions.append(mission)
        return mission

    def find_active(self, **kwargs: Any) -> dict[str, Any] | None:
        return next(
            (
                mission
                for mission in self.missions
                if mission["tag"] == kwargs["tag"]
            ),
            None,
        )

    def sync_steps(
        self, mission_id: str, steps: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {"id": mission_id, "steps": steps}

    def stop_mission(self, mission_id: str, reason: str) -> dict[str, Any]:
        return {"id": mission_id, "reason": reason}


async def fake_generate(*_args: Any, **_kwargs: Any) -> str:
    return "- Inspecter le projet\n- Exécuter les tests"


async def main() -> None:
    database_ok = FakeDatabase()
    missions = FakeMissions()
    long_tasks.configure(
        database=database_ok,
        missions=missions,
        generate=fake_generate,
        id_factory=lambda: "fixed123",
    )

    proposal = await long_tasks.start(
        {"goal": "Consolider Marvin", "_conversation_id": "conversation-1"}
    )
    assert proposal["requiresConfirmation"] is True
    assert len(proposal["steps"]) == 2
    assert database_ok.tasks == []

    started = await long_tasks.start(
        {
            "goal": "Consolider Marvin",
            "steps": proposal["steps"],
            "_conversation_id": "conversation-1",
            "confirmed": True,
        }
    )
    assert started["success"] is True
    assert started["tag"] == "longtask:consolider-marvin-fixed123"
    assert started["rollback"]["available"] is True
    assert len(database_ok.tasks) == 2
    assert len(database_ok.jobs) == 1
    assert started["mission_id"] == "mission-1"

    status = await long_tasks.status({"tag": started["tag"]})
    assert status["groups"][0]["total"] == 2
    assert status["groups"][0]["mission_id"] == "mission-1"

    stopped = await long_tasks.stop({"tag": started["tag"]})
    assert stopped["success"] is True
    assert stopped["stopped"] == 1
    assert database_ok.jobs[0]["enabled"] is False

    database_failed = FakeDatabase(fail_cron=True)
    long_tasks.configure(
        database=database_failed,
        missions=FakeMissions(),
        generate=fake_generate,
        id_factory=lambda: "rollback",
    )
    failed = await long_tasks.start(
        {
            "goal": "Tester le rollback",
            "steps": ["Étape un", "Étape deux"],
            "_conversation_id": "conversation-2",
            "confirmed": True,
        }
    )
    assert "error" in failed
    assert failed["rollback_complete"] is True
    assert database_failed.tasks == []
    assert database_failed.deleted == ["task-2", "task-1"]

    assert "4000" in (
        await long_tasks.start(
            {"goal": "x" * 4_001, "_conversation_id": "conversation-3"}
        )
    )["error"]
    assert "liste" in (
        await long_tasks.start(
            {
                "goal": "But",
                "steps": "pas une liste",
                "_conversation_id": "conversation-3",
            }
        )
    )["error"]

    long_tasks.configure(
        database=database,
        missions=mission_os,
        generate=tools._ollama_generate,
    )
    assert tools.execute_long_task_start is long_tasks.start
    assert tools.execute_long_task_status is long_tasks.status
    assert tools.execute_long_task_stop is long_tasks.stop
    assert tools.TOOLS_REGISTRY["long_task_start"] is long_tasks.start
    assert tools.TOOLS_REGISTRY["long_task_status"] is long_tasks.status
    assert tools.TOOLS_REGISTRY["long_task_stop"] is long_tasks.stop


if __name__ == "__main__":
    asyncio.run(main())
    print("Long tasks OK - plan, reprise, état, arrêt et rollback compensatoire.")
