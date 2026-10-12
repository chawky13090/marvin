"""Contrat exécutable de l'installation Windows portable et en un clic."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
    boutique_launcher = (ROOT / "PREPARER-PAQUET-BOUTIQUE.bat").read_text(encoding="utf-8")
    private_builder = (ROOT / "scripts" / "build-marvin-private-signed-package.ps1").read_text(encoding="utf-8")
    private_trust = (ROOT / "scripts" / "trust-marvin-private-publisher.ps1").read_text(encoding="utf-8")
    private_launcher = (ROOT / "scripts" / "launch-marvin-private-package.ps1").read_text(encoding="utf-8")
    package_installer = (ROOT / "scripts" / "install-marvin-package.ps1").read_text(encoding="utf-8")
    vm_qualification = (ROOT / "scripts" / "qualify-marvin-windows-package.ps1").read_text(encoding="utf-8")
    ollama_port_resolver = (ROOT / "scripts" / "resolve-ollama-port.ps1").read_text(encoding="utf-8")
    loopback_waiter = (ROOT / "scripts" / "wait-loopback-http.ps1").read_text(encoding="utf-8")
    searxng_starter = (ROOT / "docker" / "searxng" / "start-searxng.ps1").read_text(encoding="utf-8")
    assert "-StartupOrigin marvin-background" in (ROOT / "start.bat").read_text(encoding="utf-8")
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
    assert 16 * 1024**3 <= components["resume_minimum_free_bytes"] < components["minimum_free_bytes"]
    for name in ("python", "node", "ollama", "docker_desktop"):
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
        "Get-MinimumFreeBytesForCurrentRun",
        "resume_minimum_free_bytes",
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
    assert "docker_and_searxng_required" in installer
    assert "AcceptDockerDesktopLicense" in installer
    assert "Register-InstallResumeAfterRestart" in installer
    assert "MarvinInstallerResume" in installer
    assert "restart_required" in installer
    assert "DeploymentProfile = 'Full'" in installer
    docker_installer = (ROOT / "scripts" / "ensure-docker-desktop.ps1").read_text(encoding="utf-8")
    docker_grant = (ROOT / "scripts" / "grant-docker-user-access.ps1").read_text(encoding="utf-8")
    docker_wsl = (ROOT / "scripts" / "enable-docker-wsl-prerequisites.ps1").read_text(encoding="utf-8")
    assert "--accept-license" in docker_installer
    assert "--always-run-service" in docker_installer
    assert '"--user=$TargetUser"' in docker_installer
    assert "grant-docker-user-access.ps1" in docker_installer
    assert "Add-LocalGroupMember" in docker_grant
    assert "Get-LocalGroupMember" in docker_grant
    assert "docker-users" in docker_grant
    assert "Microsoft-Windows-Subsystem-Linux" in docker_wsl
    assert "VirtualMachinePlatform" in docker_wsl
    assert "Enable-WindowsOptionalFeature" in docker_wsl
    assert "--no-distribution" in docker_wsl
    assert "--web-download" in docker_wsl
    assert "Invoke-WslBounded" in docker_wsl
    assert "Test-DockerEngine" in docker_installer
    assert "StartupTimeoutSeconds" in docker_installer

    assert "git archive" in package_builder
    assert "--untracked-files=no" in package_builder
    assert "personal_data_included = $false" in package_builder
    assert "payload.zip.sha256" not in package_builder
    assert "build-marvin-windows-package.ps1" in boutique_launcher
    assert "Security.Cryptography.SHA256" in boutique_launcher
    assert "Marvin-Windows-v*.zip" in boutique_launcher
    assert "dir /b /a-d /o-d" in boutique_launcher
    assert "build-marvin-private-signed-package.ps1" in boutique_launcher
    assert "Microsoft.PowerShell.Security.psd1" in boutique_launcher
    assert "Get-AuthenticodeSignature" in boutique_launcher
    assert "robocopy" not in boutique_launcher.casefold()
    assert "rmdir" not in boutique_launcher.casefold()
    assert "function Get-Sha256Hex" in package_builder
    assert "Get-FileHash" not in package_builder
    assert "New-SelfSignedCertificate" in private_builder
    assert "KeyUsage CertSign,CRLSign,DigitalSignature" in private_builder
    assert "-Signer $RootCertificate" in private_builder
    assert "Marvin-Private-Root.cer" in private_builder
    assert "Set-AuthenticodeSignature" in private_builder
    assert "public_trust = $false" in private_builder
    assert "Microsoft.PowerShell.Security.psd1" in private_builder
    assert "Get-CertificateWithRetry" in private_builder
    assert "package-manifest.json" in private_builder
    assert "(^|[\\\\/])package-manifest\\.json$" in private_builder
    assert "Le ZIP ne provient pas du commit Git courant" in private_builder
    assert "ConvertFrom-SecureString" in private_builder
    assert "'/inheritance:r'" in private_builder
    assert "S-1-5-18" in private_builder
    assert "S-1-5-32-544" in private_builder
    assert "LocalMachine" in private_trust
    assert "-Verb RunAs" in private_trust
    assert "TrustedPublisher" in private_trust
    assert "SupportsShouldProcess" in private_trust
    assert "-Remove" in private_builder
    assert "Get-Sha256Hex" in private_launcher
    assert "Expand-Archive" in private_launcher
    assert "[System.Security.Cryptography.SHA256]::Create()" in package_installer
    assert "$Hasher.Dispose()" in package_installer
    assert "$Stream.Dispose()" in package_installer
    assert "Restore-PreviousInstall" in package_installer
    assert "data', 'runtime', '.env.local'" in package_installer
    assert "Remove-Item -LiteralPath $InstallRoot -Recurse -Force" in package_installer
    assert "Marqueur d installation Marvin absent" in uninstaller
    assert "preserved_data" in uninstaller and "shared_system_runtimes_removed = $false" in uninstaller
    assert "^Marvin\\.rollback-\\d{14}$" in uninstaller
    assert "function Remove-Bounded" in uninstaller
    assert "[IO.Directory]::Delete(`$Path, `$true)" in uninstaller
    assert "$ProtectedProcessIds" in uninstaller and "residual_process_ids_stopped" in uninstaller
    assert "taskkill.exe /PID ([int]$Process.ProcessId) /T /F" in uninstaller
    assert "removal_errors = `$RemovalErrors" in uninstaller
    assert "completion_receipt" in uninstaller and "completion_pending = $true" in uninstaller
    assert "VMCheckpoint" in vm_qualification
    assert "checkpoint_restored_after" in vm_qualification
    assert "5400000" in vm_qualification
    assert "-Confirmed" in vm_qualification
    assert "$MonitorJob = Invoke-Command -Session $MonitorSession -AsJob" in vm_qualification
    assert "Wait-Job -Job $MonitorJob -Timeout 10" in vm_qualification
    assert "Remove-Job -Job $MonitorJob" in vm_qualification
    assert "Stop-Job -Job $MonitorJob -Force" not in vm_qualification
    assert "'-NoStart'" in vm_qualification
    assert "launcher_runtime_ready = $LauncherRuntimeReady" in vm_qualification
    assert "launcher_active_when_ready = $LauncherActiveWhenReady" in vm_qualification
    assert "start_exit_code = $StartExitCode" in vm_qualification
    assert "start_stdout_tail = $StartStdoutText" in vm_qualification
    assert "$RuntimeDeadline = (Get-Date).AddMinutes(8)" in vm_qualification
    assert "-WorkingDirectory $env:SystemRoot -WindowStyle Hidden" in vm_qualification
    assert "function Set-QualificationMemoryProfile" in vm_qualification
    assert "-StartupBytes $ExpectedStartupMemoryBytes" in vm_qualification
    assert "-MinimumBytes $ExpectedMinimumMemoryBytes" in vm_qualification
    assert "-MaximumBytes $ExpectedMaximumMemoryBytes" in vm_qualification
    assert vm_qualification.count("Set-QualificationMemoryProfile -Name $VMName") == 2
    assert "$Result.memory_profile_before" in vm_qualification
    assert "$Result.memory_profile_after" in vm_qualification
    assert "[AllowEmptyCollection()]" in ollama_port_resolver
    assert "[DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)" in loopback_waiter
    assert "'127.0.0.1', 'localhost', '::1'" in loopback_waiter
    assert "Local\\Marvin.SearXNG.Startup" in searxng_starter
    assert "Local\\Marvin.SearXNG.Startup.SelfTest" in searxng_starter
    assert "function Test-DockerDaemon" in searxng_starter
    assert "function Get-ExistingSearxngPort" in searxng_starter
    assert "function Invoke-DockerComposeUp" in searxng_starter
    assert "Start-Process -FilePath $DockerPath" in searxng_starter
    assert "if ($LASTEXITCODE -ne 0 -or $portOutput.Count -eq 0)" not in searxng_starter
    assert "$Process.WaitForExit($TimeoutSeconds * 1000)" in searxng_starter
    assert "taskkill.exe /PID $Process.Id /T /F" in searxng_starter

    assert "resolve-node-runtime.ps1" in starter
    assert 'pushd "%~dp0" || exit /b 1' in starter
    assert "set \"FRONTEND_RC=%ERRORLEVEL%\"" in starter
    assert "popd\nexit /b %FRONTEND_RC%" in starter
    assert "runtime\\install\\environment.bat" in starter
    assert "wait-loopback-http.ps1" in starter
    assert "-TimeoutSeconds 240" in starter
    assert 'start "" /B powershell -NoProfile -NonInteractive -WindowStyle Hidden' in starter
    assert "runtime\\logs\\searxng-startup.log" in starter
    assert "runtime\\install\\environment.bat" in verifier
    assert "$p.WaitForExit(5000)" in verifier
    assert "Docker Desktop ne repond pas" in verifier
    assert "resolve-node-runtime.ps1" in report
    assert "function Invoke-NativeBounded" in report
    assert "$Process.WaitForExit($TimeoutMs)" in report
    assert "taskkill.exe /PID $Process.Id /T /F" in report
    assert "Invoke-NativeBounded -FilePath $DockerPath" in report
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


def _assert_ollama_port_resolver_accepts_no_exclusions() -> None:
    assert POWERSHELL, "PowerShell est requis pour le contrat Windows."
    with tempfile.TemporaryDirectory(prefix="marvin-empty-netsh-") as temp:
        fake_bin = Path(temp)
        (fake_bin / "netsh.cmd").write_text("@echo off\r\nexit /b 0\r\n", encoding="ascii")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        environment = os.environ.copy()
        environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
        result = subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / "resolve-ollama-port.ps1"),
                "-CandidatePorts",
                str(port),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
            env=environment,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip().splitlines()[-1] == str(port)


def _assert_loopback_waiter_is_bounded_and_retries() -> None:
    class DelayedReadyHandler(BaseHTTPRequestHandler):
        attempts = 0

        def do_GET(self) -> None:  # noqa: N802 - contrat de BaseHTTPRequestHandler
            type(self).attempts += 1
            status = 200 if type(self).attempts >= 3 else 503
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b"ready" if status == 200 else b"starting")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), DelayedReadyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _run_powershell(
            ROOT / "scripts" / "wait-loopback-http.ps1",
            "-Uri",
            f"http://127.0.0.1:{server.server_port}/api/tags",
            "-TimeoutSeconds",
            "10",
            "-RequestTimeoutSeconds",
            "1",
            "-PollMilliseconds",
            "100",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert DelayedReadyHandler.attempts >= 3
        assert "ready attempts=" in result.stdout
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    rejected = _run_powershell(
        ROOT / "scripts" / "wait-loopback-http.ps1",
        "-Uri",
        "https://example.invalid/api/tags",
        "-TimeoutSeconds",
        "1",
    )
    assert rejected.returncode == 2
    assert "boucle locale" in rejected.stderr


def _assert_searxng_startup_is_single_instance() -> None:
    script = ROOT / "docker" / "searxng" / "start-searxng.ps1"
    first = subprocess.Popen(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-LockSelfTest",
            "-LockSelfTestHoldMilliseconds",
            "2500",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        time.sleep(0.4)
        second = _run_powershell(script, "-LockSelfTest")
        assert second.returncode == 0, second.stdout + second.stderr
        assert "already_running" in second.stdout
        stdout, stderr = first.communicate(timeout=10)
        assert first.returncode == 0, stdout + stderr
        assert "lock_acquired" in stdout
    finally:
        if first.poll() is None:
            first.kill()
            first.wait(timeout=5)


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


def _assert_uninstall_completes_and_removes_linked_rollback() -> None:
    local_app_data = Path(os.environ["LOCALAPPDATA"])
    root = Path(tempfile.mkdtemp(prefix="Marvin-uninstall-contract-", dir=local_app_data))
    rollback = root.parent / f"Marvin.rollback-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    receipts = local_app_data / "Marvin" / "UninstallReceipts"
    before = set(receipts.glob("uninstall-*.json")) if receipts.exists() else set()
    try:
        scripts = root / "scripts"
        install = root / "runtime" / "install"
        scripts.mkdir()
        install.mkdir(parents=True)
        rollback.mkdir()
        (rollback / "old-code.txt").write_text("rollback", encoding="utf-8")
        (install / "state.json").write_text('{"status":"completed"}', encoding="utf-8")
        (install / "package.json").write_text(
            json.dumps({"schema_version": 1, "rollback_path": str(rollback)}), encoding="utf-8"
        )
        shutil.copy2(ROOT / "scripts" / "uninstall-marvin.ps1", scripts)
        (scripts / "stop-marvin.ps1").write_text(
            "[ordered]@{success=$true;state='already_stopped'}|ConvertTo-Json\nexit 0\n",
            encoding="utf-8",
        )
        command = (
            f"& '{scripts / 'uninstall-marvin.ps1'}' "
            "-RemoveData -KeepSearXngContainer -Confirm:$false"
        )
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        deadline = time.monotonic() + 30
        receipt = None
        while time.monotonic() < deadline:
            candidates = set(receipts.glob("uninstall-*.json")) - before if receipts.exists() else set()
            if candidates:
                receipt = max(candidates, key=lambda path: path.stat().st_mtime_ns)
                break
            time.sleep(0.25)
        assert receipt is not None, "Le helper de désinstallation n'a publié aucun reçu."
        evidence = json.loads(receipt.read_text(encoding="utf-8"))
        assert evidence["success"] is True and evidence["target_removed"] is True
        assert evidence["rollback_removed"] is True
        assert not root.exists() and not rollback.exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(rollback, ignore_errors=True)
        if "receipt" in locals() and receipt is not None:
            receipt.unlink(missing_ok=True)


def main() -> int:
    _assert_static_contract()
    _assert_plan_is_non_mutating()
    _assert_ollama_port_resolver_accepts_no_exclusions()
    _assert_loopback_waiter_is_bounded_and_retries()
    _assert_searxng_startup_is_single_instance()
    _assert_package_preflight_is_non_mutating()
    _assert_package_install_and_rollback_support_spaces()
    _assert_install_log_rotation_and_encoding()
    _assert_uninstall_refuses_unmarked_root()
    _assert_uninstall_completes_and_removes_linked_rollback()
    print("Installation Windows un clic OK - paquet propre, runtimes epingles, reprise, verification et desinstallation bornee.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
