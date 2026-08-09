"""Contrats de l'opérateur Windows typé et de ses postconditions."""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import action_replay
import tool_gateway
import tools
import windows_task
from config import CONDITIONAL_TOOL_SAFE_ACTIONS


async def _run() -> None:
    calls: list[tuple[str, dict]] = []

    async def process_list(args):
        calls.append(("pc_process_list", args))
        return {"success": True, "count": 2, "processes": [{"pid": 1}, {"pid": 2}]}

    async def app_launch(args):
        calls.append(("pc_app_launch", args))
        return {"success": True, "verified": True, "resolved": args["app_name"]}

    async def process_kill(args):
        calls.append(("pc_process_kill", args))
        return {
            "success": True,
            "verification": {"pid": args.get("pid"), "state": "absent"},
        }

    async def services(args):
        calls.append(("win_services_list", args))
        return {"success": True, "count": 3, "services": [{}, {}, {}]}

    async def firewall(args):
        calls.append(("win_firewall_status", args))
        return {"success": True, "profiles": [{}, {}, {}]}

    async def network(args):
        calls.append(("win_network_config", args))
        return {"success": True, "count": 1, "adapters": [{}]}

    async def software(args):
        calls.append(("winget_list_installed", args))
        return {"success": True, "count": 1, "apps": [{}]}

    async def create_folder(args):
        calls.append(("file_create_folder", args))
        Path(args["path"]).mkdir(parents=True, exist_ok=True)
        return {"success": True, "path": args["path"]}

    async def rename(args):
        calls.append(("file_rename", args))
        Path(args["source"]).rename(args["destination"])
        return {"success": True, "new_path": args["destination"]}

    async def copy(args):
        calls.append(("file_copy", args))
        shutil.copy2(args["source"], args["destination"])
        return {"success": True, "destination": args["destination"]}

    windows_task.configure(
        {
            "pc_process_list": process_list,
            "pc_app_launch": app_launch,
            "pc_process_kill": process_kill,
            "win_services_list": services,
            "win_firewall_status": firewall,
            "win_network_config": network,
            "winget_list_installed": software,
            "file_create_folder": create_folder,
            "file_rename": rename,
            "file_copy": copy,
        }
    )

    assert (await windows_task.execute({"action": "unknown"}))["error"]
    confirmation = await windows_task.execute(
        {"action": "process.stop", "pid": 123}
    )
    assert confirmation["requiresConfirmation"] is True

    for action in windows_task.READ_ACTIONS:
        result = await windows_task.execute({"action": action})
        assert result["success"] is True and result["effect_verified"] is True

    launched = await windows_task.execute(
        {"action": "application.launch", "target": "notepad", "confirmed": True}
    )
    assert launched["success"] is True
    stopped = await windows_task.execute(
        {"action": "process.stop", "pid": 123, "confirmed": True}
    )
    assert stopped["evidence"]["process_state"] == "absent"

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        folder = root / "folder"
        created = await windows_task.execute(
            {
                "action": "filesystem.create_folder",
                "target": str(folder),
                "confirmed": True,
            }
        )
        assert created["effect_verified"] is True

        source = root / "source.txt"
        renamed = root / "renamed.txt"
        source.write_text("rename", encoding="utf-8")
        renamed_result = await windows_task.execute(
            {
                "action": "filesystem.rename",
                "source": str(source),
                "destination": str(renamed),
                "confirmed": True,
            }
        )
        assert renamed_result["effect_verified"] is True

        copied = root / "copy.txt"
        copied_result = await windows_task.execute(
            {
                "action": "filesystem.copy",
                "source": str(renamed),
                "destination": str(copied),
                "confirmed": True,
            }
        )
        assert copied_result["evidence"]["sha256_equal"] is True

    async def unverifiable_launch(_args):
        return {"success": True, "verified": False}

    windows_task.configure(
        {
            "pc_process_list": process_list,
            "pc_app_launch": unverifiable_launch,
            "pc_process_kill": process_kill,
            "win_services_list": services,
            "win_firewall_status": firewall,
            "win_network_config": network,
            "winget_list_installed": software,
            "file_create_folder": create_folder,
            "file_rename": rename,
            "file_copy": copy,
        }
    )
    unverified = await windows_task.execute(
        {"action": "application.launch", "target": "notepad", "confirmed": True}
    )
    assert unverified["effect_verified"] is False
    assert unverified["needs_repair"] is True

    assert "windows_task" in tools.TOOLS_REGISTRY
    assert any(
        item["function"]["name"] == "windows_task" for item in tools.TOOLS_SPEC
    )
    assert CONDITIONAL_TOOL_SAFE_ACTIONS["windows_task"] == windows_task.READ_ACTIONS
    assert tool_gateway._conditional_mutation("windows_task", {"action": "process.list"}) is False
    assert tool_gateway._conditional_mutation("windows_task", {"action": "process.stop"}) is True
    assert action_replay.should_guard("windows_task") is True
    assert all("script" not in arguments and "command" not in arguments for _, arguments in calls)


if __name__ == "__main__":
    asyncio.run(_run())
    print("Windows Task OK - compilation typée, permissions et postconditions vérifiées.")
