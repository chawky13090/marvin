"""Persistent autonomous coding supervisor regressions without cloud calls."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import coding_jobs
import coding_mission
import coding_workspace


def git(root: Path, *args: str) -> None:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    if completed.returncode:
        raise AssertionError(completed.stderr)


def accepted_result() -> dict:
    return {
        "success": True,
        "language": "python",
        "answer": "Livrable validé.",
        "files": {"app.py": "print('auto')\n", "test_app.py": "def test_ok():\n    assert True\n"},
        "bundle": {"file_count": 2, "total_bytes": 50},
        "models_consulted": ["model-a", "model-b"],
        "families": ["a", "b"],
        "critical_issues": 0,
        "high_issues": 0,
        "test_report": {
            "production_ready": True, "tests_executed": True,
            "failed_steps": [], "steps": [{"name": "unittest", "passed": True}],
            "isolation": {"backend": "docker"},
        },
        "production_contract": {"success": True, "failures": []},
    }


async def wait_terminal(job_id: str, timeout: float = 5) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        job = coding_jobs.get_job(job_id)
        if job and job["status"] in {"completed", "failed", "cancelled", "blocked", "interrupted"}:
            return job
        await asyncio.sleep(0.02)
    raise AssertionError("Le job Auto n'a pas atteint un état terminal.")


async def scenario(repository: Path) -> None:
    async def fake_execute(_request: str, *, evidence: str = "", mission_id: str = "", defer_acceptance: bool = False) -> dict:
        assert "REPOSITORY CONTRACT" in evidence
        assert coding_mission.get(mission_id)
        return accepted_result()

    original_execute = coding_jobs.code_forge.execute
    original_retry_base = coding_jobs.RETRY_BASE_SECONDS
    coding_jobs.code_forge.execute = fake_execute
    coding_jobs.RETRY_BASE_SECONDS = 0
    try:
        mission = coding_mission.create(
            "Ajouter une application Python", target_platforms=["linux"],
            repository={"root": str(repository)}, autonomy="autonomous",
            budget={"max_duration_minutes": 5, "max_iterations": 3, "max_files_changed": 5},
        )
        workspace = coding_workspace.create(mission["id"], str(repository), confirmed=True)
        job = coding_jobs.create_job(mission["id"])
        completed = await wait_terminal(job["id"])
        assert completed["status"] == "completed", completed
        assert Path(workspace["worktree_root"], "app.py").read_text(encoding="utf-8") == "print('auto')\n"
        assert not (repository / "app.py").exists()
        assert coding_mission.get(mission["id"])["status"] == "completed"
        delivery = coding_mission.read_delivery_pack(mission["id"])
        assert delivery and delivery["status"] == "accepted"
        assert delivery["definition_of_done"]["success"] is True
        event_types = [event["type"] for event in coding_mission.stream_events(mission["id"])["events"]]
        assert "delivery.accepted" in event_types and "delivery.pack.created" in event_types

        gate = asyncio.Event()

        async def slow_execute(_request: str, *, evidence: str = "", mission_id: str = "", defer_acceptance: bool = False) -> dict:
            await gate.wait()
            return accepted_result()

        coding_jobs.code_forge.execute = slow_execute
        second = coding_mission.create(
            "Mission annulable", target_platforms=["linux"], autonomy="autonomous",
            budget={"max_duration_minutes": 5, "max_iterations": 3, "max_files_changed": 5},
        )
        coding_workspace.create(second["id"], str(repository), confirmed=True)
        cancelling = coding_jobs.create_job(second["id"])
        await asyncio.sleep(0.08)
        coding_jobs.cancel_job(cancelling["id"])
        cancelled = await wait_terminal(cancelling["id"])
        assert cancelled["status"] == "cancelled"

        coding_jobs.code_forge.execute = fake_execute
        coding_jobs._update(
            cancelling["id"], status="interrupted", cancel_requested=False,
            progress={"stage": "interrupted", "percent": 20},
        )
        assert coding_jobs.start_pending() == 1
        resumed = await wait_terminal(cancelling["id"])
        assert resumed["status"] == "completed"
        assert resumed["attempts"] == 2

        calls = 0
        repair_requests: list[str] = []
        repair_evidence: list[str] = []

        async def flaky_execute(_request: str, *, evidence: str = "", mission_id: str = "", defer_acceptance: bool = False) -> dict:
            nonlocal calls
            calls += 1
            repair_requests.append(_request)
            repair_evidence.append(evidence)
            if calls == 1:
                return {
                    "success": False, "error": "Timeout temporaire du modèle",
                    "files": {"app.py": "raise RuntimeError('candidate')\n"},
                    "test_report": {
                        "failed_steps": ["unittest"],
                        "steps": [{"name": "unittest", "passed": False, "exit_code": 1,
                                   "stderr": "AssertionError: résultat incorrect"}],
                    },
                    "production_contract": {"failures": ["tests_failed"]},
                }
            return accepted_result()

        coding_jobs.code_forge.execute = flaky_execute
        third = coding_mission.create(
            "Mission jusqu'au succès", target_platforms=["linux"], autonomy="autonomous",
            budget={"time_slice_minutes": 5, "max_consecutive_failures": 3, "max_files_changed": 5},
        )
        coding_workspace.create(third["id"], str(repository), confirmed=True)
        retrying = coding_jobs.create_job(third["id"])
        retried = await wait_terminal(retrying["id"])
        assert retried["status"] == "completed"
        assert retried["attempts"] == 2 and calls == 2
        assert "PASSE DE RÉPARATION CIBLÉE" in repair_requests[1]
        assert "AssertionError: résultat incorrect" in repair_requests[1]
        assert "UNTRUSTED_PREVIOUS_CANDIDATE" in repair_evidence[1]
        assert "raise RuntimeError('candidate')" in repair_evidence[1]
        assert retried["validation_cache"]["passed_steps"][0]["name"] == "unittest"
        assert coding_mission.get(third["id"])["completion_policy"] == "until_success"
    finally:
        coding_jobs.code_forge.execute = original_execute
        coding_jobs.RETRY_BASE_SECONDS = original_retry_base
        await coding_jobs.shutdown()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="marvin-coding-jobs-") as temporary:
        root = Path(temporary)
        repository = root / "source"
        repository.mkdir()
        (repository / "README.md").write_text("# Test\n", encoding="utf-8")
        git(repository, "init")
        git(repository, "config", "user.name", "Marvin Test")
        git(repository, "config", "user.email", "marvin-test@example.invalid")
        git(repository, "add", ".")
        git(repository, "commit", "-m", "initial")
        old_missions = coding_mission.ROOT
        old_workspaces = coding_workspace.ROOT
        old_jobs = coding_jobs.JOBS_PATH
        coding_mission.ROOT = root / "missions"
        coding_workspace.ROOT = root / "workspaces"
        coding_jobs.JOBS_PATH = root / "coding_jobs.json"
        try:
            asyncio.run(scenario(repository))
        finally:
            coding_mission.ROOT = old_missions
            coding_workspace.ROOT = old_workspaces
            coding_jobs.JOBS_PATH = old_jobs
    print("Coding Auto Supervisor OK - persistance until_success, retry, isolation, annulation et reprise.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
