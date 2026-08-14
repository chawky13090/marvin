"""Contrat exécutable de l'installation Windows portable et en un clic."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")


def _run_powershell(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL, "PowerShell est requis pour le contrat Windows."
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )


def _assert_static_contract() -> None:
    launcher = (ROOT / "INSTALLER-MARVIN.bat").read_text(encoding="utf-8")
    compatibility = (ROOT / "INSTALLER-NOUVEAU-PC.bat").read_text(encoding="utf-8")
    legacy_bat = (ROOT / "install.bat").read_text(encoding="utf-8")
    legacy_ps = (ROOT / "install.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "scripts" / "install-marvin-oneclick.ps1").read_text(encoding="utf-8")
    package_builder = (ROOT / "scripts" / "build-marvin-windows-package.ps1").read_text(encoding="utf-8")
    package_installer = (ROOT / "scripts" / "install-marvin-package.ps1").read_text(encoding="utf-8")
    vm_qualification = (ROOT / "scripts" / "qualify-marvin-windows-package.ps1").read_text(encoding="utf-8")
    uninstaller = (ROOT / "scripts" / "uninstall-marvin.ps1").read_text(encoding="utf-8")
    report = (ROOT / "scripts" / "write-install-report.ps1").read_text(encoding="utf-8")
    starter = (ROOT / "start.bat").read_text(encoding="utf-8")
    verifier = (ROOT / "VERIFIER-INSTALLATION.bat").read_text(encoding="utf-8")
    components = json.loads((ROOT / "scripts" / "windows-install-components.json").read_text(encoding="utf-8"))

    assert "install-marvin-oneclick.ps1" in launcher
    assert "INSTALLER-MARVIN.bat" in compatibility
    assert "INSTALLER-MARVIN.bat" in legacy_bat and "INSTALLER-MARVIN.bat" in legacy_ps
    assert "FERMEZ cette fenetre" not in compatibility
    assert "python.org/downloads/windows" not in compatibility
    assert "qwen3:8b" not in legacy_bat

    assert components["schema_version"] == 1
    assert components["minimum_windows_build"] >= 17763
    assert components["minimum_free_bytes"] >= 40 * 1024**3
    for name in ("python", "node", "ollama"):
        component = components[name]
        assert component["version"] and "latest" not in component["url"].casefold()
        assert component["url"].startswith("https://")
        assert len(component["sha256"]) == 64
        int(component["sha256"], 16)

    required_installer_tokens = (
        "Get-VerifiedDownload",
        "Expand-VerifiedArchive",
        "SHA-256 invalide",
        "Get-AuthenticodeSignature",
        "Join-Path $ManagedRoot 'node'",
        "Join-Path $ManagedRoot 'ollama'",
        "pip', 'check'",
        "npm_config_cache",
        "manage-data-acl.ps1",
        "plan_local_models.py",
        "qualify-local-models.py",
        "calibrate-ollama-context.py",
        "tools_count -eq 364",
        "install.log.jsonl",
        "Rotate-InstallLog",
        "start-searxng.ps1",
        "Save-State",
        "WhatIfPreference",
    )
    for token in required_installer_tokens:
        assert token in installer, token
    assert "num_ctx" not in installer
    assert "C:\\Users\\Chawb" not in installer
    assert "Invoke-WebRequest -Uri $Url" in installer
    assert "for ($Attempt = 1; $Attempt -le 3" in installer
    assert installer.count("--no-cache-dir") >= 2
    assert "Join-Path $DownloadRoot 'npm-cache'" in installer
    assert installer.count("$ErrorActionPreference = 'SilentlyContinue'") >= 3
    assert "AppendAllText" in installer and "UTF8Encoding]::new($false)" in installer
    assert "Docker absent; SearXNG reste indisponible" in installer

    assert "git archive" in package_builder
    assert "--untracked-files=no" in package_builder
    assert "personal_data_included = $false" in package_builder
    assert "payload.zip.sha256" not in package_builder
    assert "Get-FileHash" in package_installer
    assert "Restore-PreviousInstall" in package_installer
    assert "data', 'runtime', '.env.local'" in package_installer
    assert "Remove-Item -LiteralPath $InstallRoot -Recurse -Force" in package_installer
    assert "Marqueur d installation Marvin absent" in uninstaller
    assert "preserved_data" in uninstaller and "shared_system_runtimes_removed = $false" in uninstaller
    assert "VMCheckpoint" in vm_qualification
    assert "checkpoint_restored_after" in vm_qualification
    assert "5400000" in vm_qualification
    assert "-Confirmed" in vm_qualification
    assert "$MonitorJob = Invoke-Command -Session $MonitorSession -AsJob" in vm_qualification
    assert "Wait-Job -Job $MonitorJob -Timeout 10" in vm_qualification
    assert "Remove-Job -Job $MonitorJob" in vm_qualification
    assert "Stop-Job -Job $MonitorJob -Force" not in vm_qualification

    assert "resolve-node-runtime.ps1" in starter
    assert 'pushd "%~dp0" || exit /b 1' in starter
    assert "set \"FRONTEND_RC=%ERRORLEVEL%\"" in starter
    assert "popd\nexit /b %FRONTEND_RC%" in starter
    assert "runtime\\install\\environment.bat" in starter
    assert "runtime\\install\\environment.bat" in verifier
    assert "$p.WaitForExit(5000)" in verifier
    assert "Docker Desktop ne repond pas" in verifier
    assert "resolve-node-runtime.ps1" in report
    assert "resolve-ollama-exe.ps1" in report
    assert "searxng_web_search" in report


def _assert_plan_is_non_mutating() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-installer-plan-") as temp:
        root = Path(temp)
        scripts = root / "scripts"
        scripts.mkdir()
        shutil.copy2(ROOT / "scripts" / "install-marvin-oneclick.ps1", scripts)
        shutil.copy2(ROOT / "scripts" / "windows-install-components.json", scripts)
        result = _run_powershell(scripts / "install-marvin-oneclick.ps1", "-Plan")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Mode PLAN" in result.stdout
        assert "PLANIFIE" in result.stdout
        assert not (root / "runtime").exists()


def _assert_package_preflight_is_non_mutating() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-package-plan-") as temp:
        package = Path(temp) / "package"
        package.mkdir()
        payload = package / "payload.zip"
        with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("dummy.txt", "marvin")
        digest = hashlib.sha256(payload.read_bytes()).hexdigest()
        manifest = {
            "schema_version": 1,
            "source_commit": "0" * 40,
            "product_version": "test",
            "payload": {"file": "payload.zip", "sha256": digest},
            "required_files": ["dummy.txt"],
        }
        (package / "package-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        shutil.copy2(ROOT / "scripts" / "install-marvin-package.ps1", package)
        target = Path(temp) / "target-marvin"
        result = _run_powershell(package / "install-marvin-package.ps1", "-InstallRoot", str(target), "-WhatIf")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "payload verifie" in result.stdout
        assert not target.exists()


def _write_fake_package(package: Path, source_commit: str, marker: str, exit_code: int) -> None:
    package.mkdir(parents=True, exist_ok=True)
    payload = package / "payload.zip"
    fake_installer = (
        "param([switch]$NoStart,[switch]$SkipModels,[switch]$SkipOptional)\n"
        f"exit {exit_code}\n"
    )
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("scripts/install-marvin-oneclick.ps1", fake_installer)
        archive.writestr("version-marker.txt", marker)
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "source_commit": source_commit,
        "product_version": marker,
        "payload": {"file": "payload.zip", "sha256": digest},
        "required_files": ["scripts/install-marvin-oneclick.ps1", "version-marker.txt"],
    }
    (package / "package-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    shutil.copy2(ROOT / "scripts" / "install-marvin-package.ps1", package)


def _assert_package_install_and_rollback_support_spaces() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin package integration ") as temp:
        base = Path(temp)
        package = base / "package with spaces"
        target = base / "target with spaces" / "Marvin"
        _write_fake_package(package, "1" * 40, "stable", 0)
        installed = _run_powershell(
            package / "install-marvin-package.ps1",
            "-InstallRoot",
            str(target),
            "-NoStart",
            "-SkipModels",
            "-SkipOptional",
        )
        assert installed.returncode == 0, installed.stdout + installed.stderr
        assert (target / "version-marker.txt").read_text(encoding="utf-8") == "stable"
        data_marker = target / "data" / "preserved.txt"
        data_marker.parent.mkdir()
        data_marker.write_text("preserved", encoding="utf-8")

        _write_fake_package(package, "2" * 40, "broken", 7)
        failed = _run_powershell(
            package / "install-marvin-package.ps1",
            "-InstallRoot",
            str(target),
            "-NoStart",
            "-SkipModels",
            "-SkipOptional",
        )
        assert failed.returncode != 0
        assert (target / "version-marker.txt").read_text(encoding="utf-8") == "stable"
        assert data_marker.read_text(encoding="utf-8") == "preserved"


def _assert_install_log_rotation_and_encoding() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-installer-log-") as temp:
        root = Path(temp)
        scripts = root / "scripts"
        runtime = root / "runtime" / "install"
        scripts.mkdir()
        runtime.mkdir(parents=True)
        shutil.copy2(ROOT / "scripts" / "install-marvin-oneclick.ps1", scripts)
        shutil.copy2(ROOT / "scripts" / "windows-install-components.json", scripts)
        log = runtime / "install.log.jsonl"
        log.write_bytes(b"x" * (2 * 1024 * 1024))
        for index in range(1, 6):
            (runtime / f"install.log.jsonl.{index}").write_text(str(index), encoding="utf-8")
        result = _run_powershell(scripts / "install-marvin-oneclick.ps1", "-TestLogging")
        assert result.returncode == 0, result.stdout + result.stderr
        assert (runtime / "install.log.jsonl.1").stat().st_size == 2 * 1024 * 1024
        assert (runtime / "install.log.jsonl.5").read_text(encoding="utf-8") == "4"
        raw = log.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        event = json.loads(raw.decode("utf-8"))
        assert event["event_name"] == "marvin.install.stage"
        assert event["stage"] == "self_test" and event["outcome"] == "success"


def _assert_uninstall_refuses_unmarked_root() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-uninstall-plan-") as temp:
        root = Path(temp)
        scripts = root / "scripts"
        scripts.mkdir()
        shutil.copy2(ROOT / "scripts" / "uninstall-marvin.ps1", scripts)
        result = _run_powershell(scripts / "uninstall-marvin.ps1", "-WhatIf")
        assert result.returncode != 0
        assert root.exists()


def main() -> int:
    _assert_static_contract()
    _assert_plan_is_non_mutating()
    _assert_package_preflight_is_non_mutating()
    _assert_package_install_and_rollback_support_spaces()
    _assert_install_log_rotation_and_encoding()
    _assert_uninstall_refuses_unmarked_root()
    print("Installation Windows un clic OK - paquet propre, runtimes epingles, reprise, verification et desinstallation bornee.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
