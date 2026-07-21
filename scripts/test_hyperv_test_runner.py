"""Hyper-V native runner contract regressions without mutating Hyper-V."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import dpapi_secret_store
import hyperv_test_runner


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="marvin-hyperv-runner-") as temporary:
        root = Path(temporary)
        old_config = hyperv_test_runner.CONFIG_PATH
        old_secret_path = dpapi_secret_store.PATH
        old_run = hyperv_test_runner.subprocess.run
        old_powershell = hyperv_test_runner._powershell
        hyperv_test_runner.CONFIG_PATH = root / "runner.json"
        dpapi_secret_store.PATH = root / "secrets.json"
        try:
            empty = hyperv_test_runner.status()
            assert empty["ready"] is False and empty["credential_present"] is False

            observed = {
                "hyperv_access": True, "vm_exists": True, "checkpoint_exists": True,
                "vm_state": "Off", "generation": 2, "checkpoint_type": "ProductionOnly",
                "switches": ["Marvin-TestForge"],
            }

            def fake_run(*_args, **_kwargs):
                return subprocess.CompletedProcess([], 0, json.dumps(observed), "")

            hyperv_test_runner.subprocess.run = fake_run
            configured = hyperv_test_runner.configure(
                vm_name="Marvin-TestForge", checkpoint_name="Marvin-Clean",
                guest_username="MarvinRunner", guest_password="not-persisted-in-clear",
                confirmed=True,
            )
            assert configured["ready"] is True
            assert dpapi_secret_store.get_secret(hyperv_test_runner.PASSWORD_KEY) == "not-persisted-in-clear"
            assert "not-persisted-in-clear" not in dpapi_secret_store.PATH.read_text(encoding="utf-8")
            assert "not-persisted-in-clear" not in hyperv_test_runner.CONFIG_PATH.read_text(encoding="utf-8")

            envelope = {
                "guest": {
                    "success": True, "tests_executed": True, "guest_is_admin": False,
                    "steps": [{"name": "python_unittest_windows", "passed": True}],
                    "os": "Windows 11", "powershell": "5.1",
                },
                "checkpoint_restored_before": True,
                "checkpoint_restored_after": True,
                "network_disconnected_during_execution": True,
            }

            def fake_powershell(_script, *, input_text="", timeout=30):
                payload = json.loads(input_text)
                assert payload["password"] == "not-persisted-in-clear"
                return subprocess.CompletedProcess([], 0, json.dumps(envelope), "")

            hyperv_test_runner._powershell = fake_powershell
            commands = hyperv_test_runner.commands_for(
                "python", {"app.py": "print('ok')", "test_app.py": "assert True"},
            )
            assert [item["name"] for item in commands] == ["python_compile_windows", "python_unittest_windows"]
            result = hyperv_test_runner.execute(
                {"app.py": "print('ok')\n", "test_app.py": "assert True\n"},
                commands, confirmed=True,
            )
            assert result["production_ready"] is True
            assert result["isolation"]["checkpoint_restored_after"] is True
            assert result["isolation"]["network_disconnected_during_execution"] is True

            envelope["guest"]["guest_is_admin"] = True
            privileged = hyperv_test_runner.execute(
                {"app.py": "print('ok')\n"}, commands, confirmed=True,
            )
            assert privileged["production_ready"] is False
        finally:
            hyperv_test_runner.CONFIG_PATH = old_config
            dpapi_secret_store.PATH = old_secret_path
            hyperv_test_runner.subprocess.run = old_run
            hyperv_test_runner._powershell = old_powershell
    print("Hyper-V Test Runner OK - DPAPI, checkpoint, réseau coupé, PowerShell Direct et moindre privilège.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
