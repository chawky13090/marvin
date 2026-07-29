"""Persistent autonomous coding supervisor regressions without cloud calls."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


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
        "engineering_radar": {
            "available": True,
            "source_count": 1,
            "languages": ["python"],
            "sources": [{"id": "python-docs", "url": "https://docs.python.org/3/"}],
        },
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
    original_checkup_interval = coding_jobs.CHECKUP_INTERVAL_SECONDS
    coding_jobs.code_forge.execute = fake_execute
    coding_jobs.RETRY_BASE_SECONDS = 0
    coding_jobs.CHECKUP_INTERVAL_SECONDS = 0.02
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
        assert completed["privacy_contract"]["preset"] in {
            "normal", "hyper", "cloud_max", "ultra"
        }
        assert Path(workspace["worktree_root"], "app.py").read_text(encoding="utf-8") == "print('auto')\n"
        assert not (repository / "app.py").exists()
        assert coding_mission.get(mission["id"])["status"] == "completed"
        delivery = coding_mission.read_delivery_pack(mission["id"])
        assert delivery and delivery["status"] == "accepted"
        assert delivery["definition_of_done"]["success"] is True
        event_types = [event["type"] for event in coding_mission.stream_events(mission["id"])["events"]]
        assert "delivery.accepted" in event_types and "delivery.pack.created" in event_types
        assert "privacy.profile.bound" in event_types

        changed_contract = {
            "preset": "hyper",
            "cloud_only": False,
            "local_only": True,
            "sensitive_cloud_allowed": False,
        }
        with patch.object(coding_jobs, "_privacy_contract", return_value=changed_contract):
            assert coding_jobs._sync_privacy_contract(
                job["id"], mission["id"], phase="test_transition", attempt=2
            ) is True
        transition = [
            event
            for event in coding_mission.stream_events(mission["id"])["events"]
            if event["type"] == "privacy.profile.changed"
        ][-1]
        assert transition["payload"]["prior_decisions_preserved"] is True
        assert transition["payload"]["current"] == changed_contract
        privacy_mission = coding_mission.create(
            "Mission avec transition de confidentialité",
            target_platforms=["linux"],
            repository={"root": str(repository)},
            autonomy="autonomous",
            budget={
                "max_duration_minutes": 5,
                "max_iterations": 3,
                "max_files_changed": 5,
            },
        )
        coding_workspace.create(
            privacy_mission["id"], str(repository), confirmed=True
        )
        initial_contract = {
            "preset": "ultra",
            "cloud_only": True,
            "local_only": False,
            "sensitive_cloud_allowed": True,
        }
        with (
            patch.object(
                coding_jobs, "_privacy_contract", return_value=initial_contract
            ),
            patch.object(
                coding_jobs,
                "_emit",
                return_value={"proof_recorded": False},
            ),
        ):
            try:
                coding_jobs._sync_privacy_contract(
                    job["id"], mission["id"], phase="proof_failure", attempt=3
                )
            except RuntimeError as exc:
                assert "ne peut pas être prouvée" in str(exc)
            else:
                raise AssertionError(
                    "Une transition sans preuve durable devait suspendre la mission."
                )
        privacy_calls = 0

        def changing_privacy():
            nonlocal privacy_calls
            privacy_calls += 1
            return initial_contract if privacy_calls <= 2 else changed_contract

        with patch.object(
            coding_jobs, "_privacy_contract", side_effect=changing_privacy
        ):
            privacy_job = coding_jobs.create_job(privacy_mission["id"])
            privacy_completed = await wait_terminal(privacy_job["id"])
        assert privacy_completed["status"] == "completed"
        assert privacy_completed["attempts"] == 2
        privacy_events = [
            event["type"]
            for event in coding_mission.stream_events(
                privacy_mission["id"]
            )["events"]
        ]
        assert "privacy.profile.changed" in privacy_events
        assert "repair.scheduled" in privacy_events

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
        await asyncio.sleep(1.5)
        checkup_types = [
            event["type"]
            for event in coding_mission.stream_events(second["id"])["events"]
        ]
        assert "work.checkup" in checkup_types
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
        repair_types = [
            event["type"]
            for event in coding_mission.stream_events(third["id"])["events"]
        ]
        assert "repair.diagnosed" in repair_types
        assert "repair.started" in repair_types
        assert "repair.validated" in repair_types
        assert retried["result"]["documentation_manifest"]["available"] is True
        assert coding_mission.read_delivery_pack(third["id"])[
            "documentation_manifest"
        ]["source_count"] == 1

        windows_calls = 0
        windows_candidates = 0

        async def windows_execute(
            _request: str,
            *,
            evidence: str = "",
            mission_id: str = "",
            defer_acceptance: bool = False,
        ) -> dict:
            nonlocal windows_candidates
            windows_candidates += 1
            result = accepted_result()
            result["files"] = (
                {"stale.py": "raise RuntimeError('refused')\n"}
                if windows_candidates == 1
                else {"app.py": "print('windows accepted')\n"}
            )
            return result

        def native_execute(*_args, **_kwargs) -> dict:
            nonlocal windows_calls
            windows_calls += 1
            return {
                "run_id": f"windows-{windows_calls}",
                "production_ready": windows_calls > 1,
                "tests_executed": True,
                "steps": [{"name": "native", "passed": windows_calls > 1}],
                "isolation": {"backend": "hyperv"},
            }

        coding_jobs.code_forge.execute = windows_execute
        with (
            patch.object(coding_jobs.windows_validation, "route", return_value={
                "required_backend": "windows_cli_vm",
                "certification_available": True,
                "reason": "Validation Windows native requise.",
            }),
            patch.object(
                coding_jobs.hyperv_test_runner,
                "commands_for",
                return_value=[["python", "app.py"]],
            ),
            patch.object(
                coding_jobs.hyperv_test_runner,
                "execute",
                side_effect=native_execute,
            ),
        ):
            fourth = coding_mission.create(
                "Mission Windows transactionnelle",
                target_platforms=["windows"],
                autonomy="autonomous",
                budget={
                    "time_slice_minutes": 5,
                    "max_consecutive_failures": 3,
                    "max_files_changed": 5,
                },
            )
            fourth_workspace = coding_workspace.create(
                fourth["id"],
                str(repository),
                confirmed=True,
            )
            windows_job = coding_jobs.create_job(fourth["id"])
            windows_completed = await wait_terminal(windows_job["id"])
        assert windows_completed["status"] == "completed"
        assert windows_completed["attempts"] == 2
        assert windows_calls == 2 and windows_candidates == 2
        worktree = Path(fourth_workspace["worktree_root"])
        assert not (worktree / "stale.py").exists()
        assert (worktree / "app.py").read_text(encoding="utf-8") == (
            "print('windows accepted')\n"
        )
        paused_entries = [
            entry for entry in coding_mission.get(fourth["id"])["history"]
            if entry.get("phase") == "paused"
        ]
        assert paused_entries
        assert any(
            entry.get("state", {}).get("workspace_applied") is False
            for entry in paused_entries
        )

        coding_mission.record_event(
            third["id"],
            "security.redaction.test",
            {
                "error": "authorization: bearer-value",
                "password": "mission-password-value",
            },
        )
        redacted_event = coding_mission.list_events(third["id"], limit=1)[0]
        assert "bearer-value" not in str(redacted_event)
        assert "mission-password-value" not in str(redacted_event)

        with (
            patch.object(
                coding_jobs.coding_mission,
                "record_event",
                side_effect=TimeoutError("registre occupé"),
            ),
            patch.object(coding_jobs.bug_log, "log_bug") as log_bug,
        ):
            receipt = coding_jobs._emit(
                third["id"],
                "validation.proof.test",
                {"job_id": retried["id"], "secret": "ne-pas-journaliser"},
            )
        assert receipt["proof_recorded"] is False
        assert receipt["action_must_not_be_retried"] is True
        assert receipt["error_type"] == "TimeoutError"
        assert "secret" not in str(receipt)
        gaps = coding_jobs.get_job(retried["id"])["evidence_gaps"]
        assert gaps[-1]["event_type"] == "validation.proof.test"
        log_bug.assert_called_once()
    finally:
        coding_jobs.code_forge.execute = original_execute
        coding_jobs.RETRY_BASE_SECONDS = original_retry_base
        coding_jobs.CHECKUP_INTERVAL_SECONDS = original_checkup_interval
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
            durable_rows = coding_jobs._load()
            assert durable_rows
            coding_jobs._update(
                durable_rows[0]["id"],
                error="password=job-password-value",
                repair_context={"token": "job-token-value"},
            )
            persisted = coding_jobs.JOBS_PATH.read_text(encoding="utf-8")
            assert "job-password-value" not in persisted
            assert "job-token-value" not in persisted
            durable_rows = coding_jobs._load()
            backup = coding_jobs.JOBS_PATH.with_suffix(
                coding_jobs.JOBS_PATH.suffix + ".bak"
            )
            assert backup.is_file()

            coding_jobs.JOBS_PATH.write_text("{corrupt", encoding="utf-8")
            recovered = coding_jobs._load()
            assert recovered
            recovered_status = coding_jobs.store_status()
            assert recovered_status["available"] is True
            assert recovered_status["degraded"] is True
            assert recovered_status["recovered_from_backup"] is True
            coding_jobs._write(recovered)
            assert coding_jobs.store_status()["degraded"] is False

            coding_jobs.JOBS_PATH.write_text("{corrupt", encoding="utf-8")
            backup.write_text("{corrupt", encoding="utf-8")
            try:
                coding_jobs._load()
            except coding_jobs.CodingJobStoreError:
                pass
            else:
                raise AssertionError("Deux copies corrompues devaient échouer fermé.")
            assert coding_jobs.store_status()["available"] is False
            coding_jobs._write(durable_rows)
        finally:
            coding_mission.ROOT = old_missions
            coding_workspace.ROOT = old_workspaces
            coding_jobs.JOBS_PATH = old_jobs
    print("Coding Auto Supervisor OK - persistance until_success, retry, isolation, annulation et reprise.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
