"""Teste l'oracle de classement des resultats bout-en-bout Forge."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "run_windows_operator_e2e_baseline.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("forge_e2e_runner", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    runner = _load_module()
    discovery_success = {
        "toolName": "tool_search",
        "result": {"success": True, "tools": ["file_copy"]},
    }
    assert runner._classify_tool_end(discovery_success, "file_copy") == (
        False,
        False,
        False,
    )

    target_success = {
        "toolName": "file_copy",
        "result": {"success": True},
    }
    assert runner._classify_tool_end(target_success, "file_copy") == (
        True,
        False,
        False,
    )

    target_failure = {
        "toolName": "file_copy",
        "result": {"error": "destination invalide"},
    }
    assert runner._classify_tool_end(target_failure, "file_copy") == (
        False,
        True,
        False,
    )

    incidental_failure = {
        "toolName": "computer_control",
        "result": {"requiresConfirmation": True},
    }
    assert runner._classify_tool_end(incidental_failure, "file_copy") == (
        False,
        False,
        True,
    )
    print("Windows operator E2E classifier OK - discovery is not a business claim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
