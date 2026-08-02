"""Regression tests for prompt-first Code Workspace and chat parity."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import coding_scratch
import coding_service
import coding_mission
import tools


def main() -> int:
    assert coding_service.infer_targets("script Bash pour Debian 13") == ["linux"]
    assert coding_service.infer_targets("application WPF pour Windows 11") == ["windows"]
    assert coding_service.infer_targets("bibliothèque Python portable") == ["windows", "linux"]

    with tempfile.TemporaryDirectory(prefix="marvin-coding-service-") as temporary:
        machine = Path(temporary) / "machine"
        exports = Path(temporary) / "exports"
        machine.mkdir()
        exports.mkdir()
        with (
            patch.object(coding_scratch.storage_layout, "roots", return_value=(machine, exports)),
            patch.object(coding_scratch.storage_layout, "ensure", return_value={"machine_root": str(machine)}),
        ):
            contract = coding_scratch.create("Créer un script Debian fiable", confirmed=True)
        repository = Path(contract["root"])
        assert repository.is_dir()
        assert repository.parent == (machine / "workspaces" / "code" / "requests")
        assert contract["git"]["available"] is True
        assert not contract["git"]["dirty"]
        head = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            capture_output=True, text=True, errors="replace", check=False, timeout=10,
        )
        assert head.returncode == 0 and head.stdout.strip()

    confirmation = coding_service.start("Créer un script Debian", confirmed=False)
    assert confirmation["requiresConfirmation"] is True

    fake_contract = {
        "root": "C:/isolated/project", "name": "project", "contract_hash": "abc",
        "git": {"head": "123", "dirty": False}, "instructions": [],
    }
    fake_mission = {"id": "a" * 32, "request": "Créer un script Debian", "status": "planned"}
    with (
        patch.object(coding_service.coding_scratch, "create", return_value=fake_contract),
        patch.object(coding_service.coding_mission, "create", return_value=fake_mission) as create_mission,
        patch.object(coding_service.coding_workspace, "create", return_value={"worktree_root": "C:/worktree"}),
        patch.object(coding_service.coding_jobs, "create_job", return_value={"id": "job-1"}),
    ):
        started = coding_service.start("Créer un script Debian", confirmed=True)
    assert started["success"] is True
    assert started["mission_id"] == "a" * 32
    assert started["job_id"] == "job-1"
    assert started["scratch_repository"] is True
    assert started["target_platforms"] == ["linux"]
    assert create_mission.call_args.kwargs["target_platforms"] == ["linux"]

    mission_id = "b" * 32
    with (
        patch.object(coding_service.coding_mission, "get", return_value={"id": mission_id}),
        patch.object(coding_service.coding_mission, "latest_manifest", return_value=[{"path": "main.sh"}]),
        patch.object(coding_service.coding_mission, "list_events", return_value=[
            {"type": "repair.diagnosed", "payload": {"attempt": 1}},
            {"type": "work.checkup", "payload": {"stage": "test_forge"}},
        ]),
        patch.object(coding_service.coding_mission, "latest_files", return_value={"main.sh": "#!/bin/bash\ntrue\n"}),
        patch.object(coding_service.coding_workspace, "get", return_value=None),
        patch.object(coding_service.coding_jobs, "latest_for_mission", return_value={"status": "blocked"}),
        patch.object(coding_service, "_execution_capabilities", return_value={"docker_linux": {"available": True}}),
    ):
        detailed = coding_service.status(mission_id)
    assert detailed["artifacts"]["source"] == "mission_snapshot"
    assert detailed["success"] is True
    assert detailed["mission_id"] == mission_id
    assert len(detailed["repair_ledger"]) == 1
    assert detailed["repair_ledger"][0]["type"] == "repair.diagnosed"
    assert detailed["artifacts"]["files"][0]["path"] == "main.sh"
    assert "#!/bin/bash" in detailed["artifacts"]["files"][0]["content"]
    assert detailed["execution_capabilities"]["docker_linux"]["available"] is True
    code_page = (ROOT / "app" / "code" / "page.jsx").read_text(encoding="utf-8")
    assert "overview?.job_store?.degraded" in code_page
    assert "dernière sauvegarde valide" in code_page

    snapshot_id = "c" * 32
    missing_snapshot_path = ROOT / "data" / "coding_workspaces" / snapshot_id / "repo" / "test.sh"
    with patch.object(coding_mission, "latest_files", return_value={"test.sh": "#!/bin/bash\ntrue\n"}):
        snapshot_read = asyncio.run(tools.execute_file_read({"path": str(missing_snapshot_path)}))
    assert snapshot_read["success"] is True
    assert snapshot_read["source"] == "mission_snapshot"
    assert snapshot_read["mission_id"] == snapshot_id
    assert snapshot_read["path"] == "test.sh"

    for name in ("code_workspace_start", "code_workspace_status", "code_workspace_control"):
        assert name in tools.TOOLS_REGISTRY
        assert name in {item["function"]["name"] for item in tools.TOOLS_SPEC}

    def start_on_event_loop(*args, **kwargs):
        assert asyncio.get_running_loop().is_running()
        return {"success": True, "project": {"id": "mission-loop"}}

    def control_on_event_loop(*args, **kwargs):
        assert asyncio.get_running_loop().is_running()
        return {"success": True, "job": {"id": "job-loop"}}

    with patch.object(coding_service, "start", side_effect=start_on_event_loop):
        chat_start = asyncio.run(tools.execute_code_workspace_start({
            "request": "Créer un script Debian", "confirmed": True,
        }))
    assert chat_start["success"] is True
    with patch.object(coding_service, "control", side_effect=control_on_event_loop):
        chat_control = asyncio.run(tools.execute_code_workspace_control({
            "mission_id": "mission-loop", "action": "resume", "confirmed": True,
        }))
    assert chat_control["success"] is True

    print("Coding Service OK - prompt direct, dépôt isolé, cible Debian et parité chat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
