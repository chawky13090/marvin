"""Régressions déterministes du domaine de sécurité des commandes."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import command_safety


async def _run() -> None:
    original_rules = command_safety.db.cmd_rules_list
    original_review_list = command_safety.db.cmd_review_list
    try:
        command_safety.db.cmd_rules_list = lambda active_only=True: [{
            "pattern": r"rm\s+-rf",
            "risk_level": "blocked",
            "platform": "linux",
            "explanation": "Suppression récursive",
            "safer_alternative": "Supprimer une cible validée.",
        }]
        command_safety.db.cmd_review_list = lambda *_args, **_kwargs: []

        assert command_safety._detect_command_platform("Get-Service") == "powershell"
        assert command_safety._detect_command_platform("sudo systemctl status ssh") == "linux"
        assert command_safety._analyze_command_risk("rm -rf /")["risk_level"] == "blocked"
        assert "text" in (
            await command_safety.execute_cmd_extract_from_text({"text": 42})
        )["error"]
        extracted = await command_safety.execute_cmd_extract_from_text(
            {"text": "Diagnostic\n$ Get-Service\nsudo systemctl status ssh"}
        )
        assert extracted["commands"] == ["Get-Service", "sudo systemctl status ssh"]
        assert "liste attendue" in (
            await command_safety.execute_cmd_analyze_risk({"commands": "rm -rf /"})
        )["error"]
        assert "limit" in (
            await command_safety.execute_cmd_review_history({"limit": 0})
        )["error"]

        public_names = [
            name.removeprefix("execute_")
            for name in dir(command_safety)
            if name.startswith("execute_cmd_")
        ]
        assert len(public_names) == 5
        for public_name in public_names:
            implementation = getattr(command_safety, f"execute_{public_name}")
            assert getattr(tools, f"execute_{public_name}") is implementation
            assert tools.TOOLS_REGISTRY[public_name] is implementation
        assert tools._analyze_command_risk is command_safety._analyze_command_risk
    finally:
        command_safety.db.cmd_rules_list = original_rules
        command_safety.db.cmd_review_list = original_review_list


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine sécurité des commandes OK")
