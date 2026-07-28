"""Régressions Test Forge sans lancer Docker."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import test_forge
import tools


def _passed_step(name: str) -> dict:
    return {
        "name": name,
        "passed": True,
        "exit_code": 0,
        "duration_ms": 10,
        "stdout": "",
        "stderr": "",
        "image": "test@sha256:abc",
    }


def main() -> int:
    assert test_forge._validate_integration_runtime_contract(
        "python",
        "DEBIAN_FRONTEND=noninteractive apt-get install -y python3.12 python3.12-venv\n"
        "echo MARVIN_INTEGRATION_COMPLETE=full\n",
    )
    assert test_forge._validate_integration_runtime_contract(
        "python",
        "python3 -m unittest discover -s tests\n"
        "echo MARVIN_INTEGRATION_COMPLETE=full\n",
    ) is None
    assert test_forge.requires_native_linux_runtime(
        "    systemctl restart nginx", "bash"
    ), "Une commande systemctl indentée doit être routée vers la VM Debian native."

    command = test_forge._base_command("docker", "image@sha256:abc", Path.cwd())
    assert "--network" in command and "none" in command
    assert "--pull" in command and "never" in command
    assert "--read-only" in command
    assert "--cap-drop" in command and "ALL" in command
    assert "no-new-privileges=true" in command
    assert "/var/run/docker.sock" not in " ".join(command)

    with (
        patch.object(
            test_forge,
            "docker_status",
            return_value={"available": True, "executable": "docker", "server_version": "29.6.1"},
        ),
        patch.object(
            test_forge,
            "_run",
            side_effect=[
                _passed_step("bash_syntax"),
                _passed_step("shellcheck"),
                _passed_step("bats"),
            ],
        ),
    ):
        result = test_forge.execute(
            "#!/usr/bin/env bash\nset -Eeuo pipefail\n",
            "bash",
            test_code='@test "ok" { run true; [ "$status" -eq 0 ]; }\n',
        )
    assert result["production_ready"] is True
    assert result["tests_executed"] is True
    assert result["isolation"]["network"] == "none"
    assert result["isolation"]["docker_socket_mounted"] is False
    assert result["isolation"]["offline"]["read_only_rootfs"] is True

    with (
        patch.object(
            test_forge,
            "docker_status",
            return_value={"available": True, "executable": "docker", "server_version": "29.6.1"},
        ),
        patch.object(
            test_forge,
            "_run",
            side_effect=[
                _passed_step("bash_syntax"),
                _passed_step("shellcheck"),
                _passed_step("bats"),
            ],
        ),
        patch.object(
            test_forge,
            "_run_online_integration",
            return_value={
                **_passed_step("online_integration"),
                "network": "bridge",
                "completion_marker": True,
                "test_completion_marker": True,
            },
        ),
    ):
        online = test_forge.execute(
            "#!/usr/bin/env bash\nset -Eeuo pipefail\n",
            "bash",
            test_code='@test "ok" { run true; [ "$status" -eq 0 ]; }\n',
            integration_test_code=(
                "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
                "bash ./main.sh --integration-test\n"
                "echo MARVIN_INTEGRATION_COMPLETE=full\n"
            ),
            require_online=True,
        )
    assert online["production_ready"] is True
    assert online["online_executed"] is True
    assert "integration:bridge" in online["isolation"]["network"]
    assert online["isolation"]["published_ports"] is False
    assert online["isolation"]["online"]["privileged"] is False

    with (
        patch.object(
            test_forge,
            "docker_status",
            return_value={"available": True, "executable": "docker", "server_version": "29.6.1"},
        ),
        patch.object(
            test_forge,
            "_run",
            side_effect=[
                _passed_step("bash_syntax"), _passed_step("shellcheck"),
                _passed_step("bats"),
            ],
        ),
    ):
        installer_without_integration = test_forge.execute(
            "#!/usr/bin/env bash\nset -Eeuo pipefail\napt-get install -y zabbix-agent2\n",
            "bash",
            test_code='@test "mentions package" { grep -q zabbix-agent2 /workspace/main.sh; }\n',
        )
    assert installer_without_integration["production_ready"] is False
    assert installer_without_integration["online_required"] is True
    assert installer_without_integration["online_requirement_reason"] == "installer_detected"
    assert "online_integration_required" in installer_without_integration["failed_steps"]

    with (
        patch.object(
            test_forge,
            "docker_status",
            return_value={"available": True, "executable": "docker", "server_version": "29.6.1"},
        ),
        patch.object(
            test_forge,
            "_run",
            side_effect=[
                _passed_step("bash_syntax"), _passed_step("shellcheck"),
                _passed_step("bats"),
            ],
        ),
        patch.object(
            test_forge.linux_test_runner,
            "execute",
            return_value={
                "success": True, "production_ready": True, "tests_executed": True,
                "result_snapshot_available": True,
                "steps": [{**_passed_step("native_debian_vm"), "test_completion_marker": True}],
                "isolation": {"checkpoint_restored_before": True, "checkpoint_restored_after": True},
            },
        ) as native_execute,
    ):
        native_systemd = test_forge.execute(
            "#!/usr/bin/env bash\nset -Eeuo pipefail\nsystemctl is-active --quiet ssh\n",
            "bash",
            test_code='@test "systemd" { run grep -q systemctl /workspace/main.sh; [ "$status" -eq 0 ]; }\n',
            integration_test_code=(
                "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
                "systemctl is-active --quiet ssh\n"
                "echo MARVIN_INTEGRATION_COMPLETE=full\n"
            ),
        )
    assert native_systemd["production_ready"] is True
    assert native_systemd["online_requirement_reason"] == "native_linux_runtime"
    assert native_systemd["result_snapshot_available"] is True
    assert native_systemd["isolation"]["network"] == "offline:none; native_vm:default_switch"
    native_execute.assert_called_once()

    with (
        patch.object(
            test_forge,
            "docker_status",
            return_value={"available": True, "executable": "docker", "server_version": "29.6.1"},
        ),
        patch.object(
            test_forge,
            "_run",
            side_effect=[
                _passed_step("python_compile"),
                _passed_step("python_unittest"),
            ],
        ),
        patch.object(
            test_forge,
            "_run_online_integration",
            return_value={
                **_passed_step("online_integration"),
                "network": "bridge",
                "completion_marker": True,
                "test_completion_marker": True,
            },
        ),
    ):
        python_online = test_forge.execute(
            "def value(): return 42\n",
            "python",
            test_code="import unittest\nclass T(unittest.TestCase):\n def test_value(self): self.assertTrue(True)\n",
            integration_test_code=(
                "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
                "python ./test_main.py\n"
                "echo MARVIN_INTEGRATION_COMPLETE=full\n"
            ),
            require_online=True,
        )
    assert python_online["production_ready"] is True
    assert python_online["online_executed"] is True

    assert "chemin absolu" in test_forge._validate_integration_shape(
        "#!/bin/bash\nbash /work/src/main.sh\necho MARVIN_INTEGRATION_COMPLETE=full\n"
    )
    assert test_forge._validate_integration_shape(
        "#!/bin/bash\nbash ./main.sh\necho MARVIN_INTEGRATION_COMPLETE=full\n"
    ) is None

    with (
        patch.object(
            test_forge,
            "docker_status",
            return_value={"available": True, "executable": "docker", "server_version": "29.6.1"},
        ),
        patch.object(
            test_forge,
            "_run",
            side_effect=[
                _passed_step("python_compile"),
                _passed_step("python_unittest"),
            ],
        ),
    ):
        unlocked = test_forge.execute(
            "from src.service import value\n",
            "python",
            test_code="import unittest\nclass T(unittest.TestCase):\n def test_value(self): self.assertTrue(True)\n",
            files={
                "src/service.py": "def value(): return 42\n",
                "pyproject.toml": '[project]\nname="sample"\ndependencies=["httpx"]\n',
            },
        )
    assert unlocked["production_ready"] is False
    assert "python_dependencies_locked" in unlocked["failed_steps"]

    unsafe_bundle = test_forge.execute(
        "print('x')\n",
        "python",
        test_code="import unittest\n",
        files={"../escape.py": "x = 1\n"},
    )
    assert unsafe_bundle["production_ready"] is False
    assert unsafe_bundle["failed_steps"] == ["bundle_paths_safe"]

    with (
        patch.object(
            test_forge,
            "docker_status",
            return_value={"available": True, "executable": "docker", "server_version": "29.6.1"},
        ),
        patch.object(
            test_forge,
            "_run",
            side_effect=[
                _passed_step("python_compile"),
            ],
        ),
    ):
        missing_tests = test_forge.execute("x = 1\n", "python")
    assert missing_tests["production_ready"] is False
    assert "test_suite_required" in missing_tests["failed_steps"]

    invalid_json = test_forge.execute("{", "json")
    assert invalid_json["production_ready"] is False
    valid_json = test_forge.execute('{"ok": true}', "json")
    assert valid_json["production_ready"] is True

    with (
        patch.object(
            test_forge,
            "docker_status",
            return_value={"available": True, "executable": "docker", "server_version": "29.6.1"},
        ),
        patch.object(
            test_forge,
            "_run",
            side_effect=[_passed_step("gofmt"), _passed_step("go_vet"), _passed_step("go_test"), _passed_step("go_build_windows")],
        ),
    ):
        go_result = test_forge.execute(
            "package main\nfunc Double(v int) int { return v * 2 }\nfunc main() {}\n",
            "go",
            test_code=(
                "package main\nimport \"testing\"\n"
                "func TestDouble(t *testing.T) { if Double(21) != 42 { t.Fatal(\"bad\") } }\n"
            ),
            files={"go.mod": "module example.com/marvin/sample\n\ngo 1.26\n"},
        )
    assert go_result["production_ready"] is True
    assert go_result["tests_executed"] is True

    powershell = test_forge.execute("Write-Output 'ok'", "powershell")
    assert powershell["production_ready"] is False
    assert "Windows" in powershell["error"]

    assert "ai_test_forge" in tools.TOOLS_REGISTRY
    assert "ai_test_forge" in {item["function"]["name"] for item in tools.TOOLS_SPEC}
    print("Test Forge OK - isolation Docker, intégration web et refus PowerShell non isolé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
