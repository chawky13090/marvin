"""Prouve que resume et cancel suivent des branches métier distinctes."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import coding_service


def main() -> int:
    job = {"id": "coding-job-fixture", "status": "blocked"}
    mission = {"id": "mission-fixture"}

    with (
        patch.object(coding_service.coding_jobs, "latest_for_mission", return_value=job),
        patch.object(
            coding_service.coding_jobs,
            "cancel_job",
            return_value={**job, "cancel_requested": True},
        ) as cancel,
        patch.object(coding_service.coding_jobs, "resume_job") as resume,
        patch.object(coding_service.coding_mission, "get", return_value=mission),
    ):
        cancelled = coding_service.control("mission-fixture", "cancel", confirmed=True)
    assert cancelled["success"] is True
    cancel.assert_called_once_with("coding-job-fixture")
    resume.assert_not_called()

    with (
        patch.object(coding_service.coding_jobs, "latest_for_mission", return_value=job),
        patch.object(coding_service.coding_jobs, "cancel_job") as cancel,
        patch.object(
            coding_service.coding_jobs,
            "resume_job",
            return_value={**job, "status": "queued"},
        ) as resume,
        patch.object(coding_service.coding_mission, "get", return_value=mission),
    ):
        resumed = coding_service.control("mission-fixture", "resume", confirmed=True)
    assert resumed["success"] is True
    resume.assert_called_once_with("coding-job-fixture")
    cancel.assert_not_called()

    with patch.object(coding_service.coding_jobs, "latest_for_mission") as latest:
        confirmation = coding_service.control(
            "mission-fixture",
            "resume",
            confirmed=False,
        )
    assert confirmation["requiresConfirmation"] is True
    latest.assert_not_called()

    print("TD-014 Action Surfaces OK - resume/cancel séparés et confirmation fermée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
