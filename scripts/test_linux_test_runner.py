"""Debian Hyper-V runner contract regressions without mutating Hyper-V."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import dpapi_secret_store
import linux_test_runner


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="marvin-linux-runner-") as temporary:
        root = Path(temporary)
        old_state = linux_test_runner.STATE_PATH
        old_install_result = linux_test_runner.INSTALL_RESULT_PATH
        old_secret_path = dpapi_secret_store.PATH
        old_powershell = linux_test_runner._powershell
        linux_test_runner.STATE_PATH = root / "state.json"
        linux_test_runner.INSTALL_RESULT_PATH = root / "install.json"
        dpapi_secret_store.PATH = root / "secrets.json"
        try:
            observed = {
                "hyperv_access": True, "vm_exists": True, "checkpoint_exists": True,
                "vm_state": "Off", "result_checkpoints": [], "switches": ["Default Switch"],
                "host_free_memory_bytes": 8 * 1024**3,
                "memory_startup_bytes": 4 * 1024**3,
            }

            def status_powershell(_script, *, input_text="", timeout=30):
                return subprocess.CompletedProcess([], 0, json.dumps(observed), "")

            linux_test_runner._powershell = status_powershell
            assert linux_test_runner.status()["ready"] is False
            dpapi_secret_store.set_secret(linux_test_runner.KEY_SECRET, "test-private-key")
            linux_test_runner.INSTALL_RESULT_PATH.write_text(
                json.dumps({"native_runner_version": 1}), encoding="utf-8",
            )
            assert linux_test_runner.status()["ready"] is True
            observed["host_free_memory_bytes"] = 1024**3
            low_memory = linux_test_runner.status()
            assert low_memory["ready"] is False
            assert low_memory["memory_ready"] is False
            assert "Mémoire hôte insuffisante" in low_memory["error"]
            observed["host_free_memory_bytes"] = 8 * 1024**3
            incomplete = linux_test_runner.execute({"main.sh": "#!/bin/bash\ntrue\n"})
            assert incomplete["production_ready"] is False
            assert "integration.sh" in incomplete["error"]

            envelope = {
                "exit_code": 0,
                "stdout": "1..1\nok 1 integration\nMARVIN_NATIVE_LINUX_COMPLETE=full",
                "stderr": "",
                "checkpoint_restored_before": True,
                "checkpoint_restored_after": True,
                "result_checkpoint": "Marvin-Result-linux-forge-aaaaaaaaaaaa",
                "network_used_for_guest": True,
                "host_network_modified": False,
            }

            def execute_powershell(script, *, input_text="", timeout=30):
                if script == linux_test_runner._STATUS_SCRIPT:
                    return subprocess.CompletedProcess([], 0, json.dumps(observed), "")
                assert "Get-ChildItem -LiteralPath" in script
                assert "+ '\\.'" not in script
                assert "$previousErrorPreference = $ErrorActionPreference" in script
                assert "$ErrorActionPreference = 'Continue'" in script
                assert "$exitCode = $LASTEXITCODE" in script
                payload = json.loads(input_text)
                assert payload["run_id"].startswith("linux-forge-")
                assert "test-private-key" not in input_text
                envelope["result_checkpoint"] = "Marvin-Result-" + payload["run_id"]
                return subprocess.CompletedProcess([], 0, json.dumps(envelope), "")

            linux_test_runner._powershell = execute_powershell
            result = linux_test_runner.execute({
                "main.sh": "#!/bin/bash\ntrue\n",
                "integration.sh": "#!/bin/bash\ntrue\n",
                "test_main.bats": "@test ok { true; }\n",
            })
            assert result["production_ready"] is True
            assert result["isolation"]["checkpoint_restored_before"] is True
            assert result["isolation"]["checkpoint_restored_after"] is True
            assert result["isolation"]["host_network_modified"] is False
            state = linux_test_runner._read_state()
            assert state["status"] == "result_available"

            run_id = state["run_id"]

            def session_powershell(_script, *, input_text="", timeout=30):
                payload = json.loads(input_text)
                return subprocess.CompletedProcess([], 0, json.dumps({
                    "success": True, "action": payload["action"],
                    "vm_state": "Running" if payload["action"] == "open" else "Off",
                }), "")

            linux_test_runner._powershell = session_powershell
            opened = linux_test_runner.open_result(run_id=run_id, confirmed=True)
            assert opened["session"]["status"] == "manual_active"
            restored = linux_test_runner.restore_clean(confirmed=True)
            assert restored["session"]["status"] == "clean"
        finally:
            linux_test_runner.STATE_PATH = old_state
            linux_test_runner.INSTALL_RESULT_PATH = old_install_result
            dpapi_secret_store.PATH = old_secret_path
            linux_test_runner._powershell = old_powershell
    print("Linux Test Runner OK - checkpoint propre, exécution Debian, résultat inspectable et restauration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
