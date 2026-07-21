"""Régressions déterministes du runner Windows Sandbox, sans lancer de VM."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import windows_test_runner


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        input_directory = root / "input"
        output_directory = root / "output"
        input_directory.mkdir()
        output_directory.mkdir()
        config = windows_test_runner.build_wsb(input_directory, output_directory)
        assert "<Networking>Enable</Networking>" in config
        assert "<VGpu>Disable</VGpu>" in config
        assert "<ClipboardRedirection>Disable</ClipboardRedirection>" in config
        assert "<ReadOnly>true</ReadOnly>" in config
        assert "<ReadOnly>false</ReadOnly>" in config
        assert "bootstrap.ps1" in config
    bootstrap = windows_test_runner._bootstrap_script()
    assert "192.168.0.0/16" in bootstrap
    assert "fc00::/7" in bootstrap
    assert "-Program $program" in bootstrap
    assert "WindowsPowerShell\\v1.0\\powershell.exe" in bootstrap
    assert "Install-Module Pester -RequiredVersion 5.8.0" in bootstrap
    assert "-ForceBootstrap" in bootstrap
    assert "$ConfirmPreference = 'None'" in bootstrap
    assert "Invoke-Pester" in bootstrap
    assert "@($findings).Count" in bootstrap
    assert "result.json" in bootstrap
    source = (ROOT / "backend" / "windows_test_runner.py").read_text(encoding="utf-8")
    assert "_sandbox_process_ids" in source
    assert "Une instance Windows Sandbox est deja ouverte" in source
    assert "_stop_owned_sandbox_processes" in source
    assert "deliverable_bundle.normalize_path" in source
    print("Windows Test Runner OK - WSB, garde réseau, modules épinglés et Pester.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
