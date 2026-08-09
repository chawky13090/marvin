"""Contrats de l'opérateur Windows typé et de ses postconditions."""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import action_replay
import tool_gateway
import tools
import windows_task
from config import (
    CONDITIONAL_TOOL_SAFE_ACTIONS,
    CONDITIONAL_TOOL_STANDARD_ACTIONS,
    PERMISSION_SECURE,
    PERMISSION_STANDARD,
)


async def _run() -> None:
    policy_conversation_id = f"windows-task-policy-{uuid.uuid4()}"
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

    await windows_task.execute({"action": "process.list", "sort_by": "cpu"})
    await windows_task.execute(
        {"action": "service.list", "filter": "print", "status": "running"}
    )
    await windows_task.execute({"action": "software.list", "query": "VLC"})
    assert ("pc_process_list", {"sort_by": "cpu"}) in calls
    assert (
        "win_services_list",
        {"filter": "print", "status": "running"},
    ) in calls
    assert ("winget_list_installed", {"query": "VLC"}) in calls

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
    assert CONDITIONAL_TOOL_STANDARD_ACTIONS["windows_task"] == (
        windows_task.READ_ACTIONS
        | {
            "application.launch",
            "filesystem.create_folder",
            "filesystem.rename",
            "filesystem.copy",
        }
    )
    assert tool_gateway._conditional_mutation("windows_task", {"action": "process.list"}) is False
    assert tool_gateway._conditional_mutation("windows_task", {"action": "process.stop"}) is True
    assert tool_gateway._conditional_mutation("windows_task", {"action": "filesystem.copy"}) is True
    assert tool_gateway._conditional_requires_confirmation(
        "windows_task", {"action": "filesystem.copy"}
    ) is False
    assert tool_gateway._conditional_requires_confirmation(
        "windows_task", {"action": "process.stop"}
    ) is True
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
    specification = [
        item for item in tools.TOOLS_SPEC
        if item["function"]["name"] == "windows_task"
    ]

    class Database:
        @staticmethod
        def log_execution(*_args, **_kwargs):
            return None

    async def gateway_call(action_args, permission_level):
        return await tool_gateway.execute_tool(
            tool_gateway.ToolGatewayRequest(
                tool_name="windows_task",
                arguments=action_args,
                source="test",
                permission_level=permission_level,
                conversation_id=policy_conversation_id,
            ),
            registry={"windows_task": windows_task.execute},
            specifications=specification,
            database=Database,
            normalizer=lambda _name, result, **_kwargs: result,
            audit_logger=lambda *_args, **_kwargs: None,
        )

    standard_launch = await gateway_call(
        {"action": "application.launch", "target": "notepad"},
        PERMISSION_STANDARD,
    )
    assert standard_launch.executed is True
    assert standard_launch.result.get("effect_verified") is True, standard_launch.result
    assert standard_launch.result.get("requiresConfirmation") is not True
    secure_launch = await gateway_call(
        {"action": "application.launch", "target": "notepad"},
        PERMISSION_SECURE,
    )
    assert secure_launch.executed is False
    assert secure_launch.result.get("permission_denied") is True
    standard_stop = await gateway_call(
        {"action": "process.stop", "pid": 4242},
        PERMISSION_STANDARD,
    )
    assert standard_stop.executed is False
    assert standard_stop.result.get("requiresConfirmation") is True
    assert action_replay.should_guard("windows_task") is True
    assert all("script" not in arguments and "command" not in arguments for _, arguments in calls)


if __name__ == "__main__":
    asyncio.run(_run())
    print("Windows Task OK - compilation typée, permissions et postconditions vérifiées.")
