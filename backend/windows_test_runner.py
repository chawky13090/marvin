"""Disposable Windows Sandbox runner for PowerShell deliverables."""
from __future__ import annotations

import html
import csv
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import deliverable_bundle


def sandbox_executable() -> Path | None:
    candidate = shutil.which("WindowsSandbox.exe")
    if candidate:
        return Path(candidate)
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    path = system_root / "System32" / "WindowsSandbox.exe"
    return path if path.exists() else None


def status() -> dict[str, Any]:
    executable = sandbox_executable()
    return {
        "available": executable is not None,
        "backend": "windows_sandbox" if executable else None,
        "executable": str(executable) if executable else None,
        "network_mode": "internet_with_private_ranges_blocked_for_test_processes",
        "input_mount": "read_only",
        "output_mount": "temporary_write_only",
        "single_instance": True,
        "hyper_v_service": _service_running("vmms"),
        "error": None if executable else (
            "Windows Sandbox n'est pas activé. Activez Containers-DisposableClientVM "
            "puis redémarrez Windows."
        ),
    }


def _service_running(name: str) -> bool:
    try:
        completed = subprocess.run(
            ["sc.exe", "query", name],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=10,
            check=False,
        )
        return completed.returncode == 0 and "RUNNING" in completed.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def _sandbox_process_ids() -> set[int]:
    process_ids: set[int] = set()
    for image_name in ("WindowsSandboxServer.exe", "WindowsSandboxRemoteSession.exe"):
        try:
            completed = subprocess.run(
                ["tasklist.exe", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode != 0:
            continue
        for row in csv.reader(io.StringIO(completed.stdout)):
            if len(row) < 2 or row[0].lower() != image_name.lower():
                continue
            try:
                process_ids.add(int(row[1].replace(",", "")))
            except ValueError:
                continue
    return process_ids


def _stop_owned_sandbox_processes(process_ids: set[int]) -> None:
    for process_id in sorted(process_ids):
        try:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process_id), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue


def _wait_for_sandbox_exit(process_ids: set[int], timeout_seconds: int = 30) -> None:
    deadline = time.monotonic() + max(1, timeout_seconds)
    while process_ids.intersection(_sandbox_process_ids()) and time.monotonic() < deadline:
        time.sleep(0.5)


def _bootstrap_script() -> str:
    return r"""Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$ConfirmPreference = 'None'
$result = [ordered]@{
    success = $false
    production_ready = $false
    tests_executed = $false
    network = 'internet_private_ranges_blocked_for_test_processes'
    steps = @()
}

function Add-Step {
    param([string]$Name, [bool]$Passed, [int]$ExitCode, [string]$Detail)
    $script:result.steps += [ordered]@{
        name = $Name
        passed = $Passed
        exit_code = $ExitCode
        detail = $Detail
    }
}

try {
    $privateRanges = @(
        '10.0.0.0/8', '100.64.0.0/10', '169.254.0.0/16',
        '172.16.0.0/12', '192.168.0.0/16', '224.0.0.0/4',
        'fc00::/7', 'fe80::/10', 'ff00::/8'
    )
    $guardedPrograms = @(
        "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe",
        "$env:SystemRoot\System32\cmd.exe",
        "$env:SystemRoot\System32\curl.exe",
        "$env:SystemRoot\System32\certutil.exe",
        "$env:SystemRoot\System32\bitsadmin.exe",
        "$env:SystemRoot\System32\msiexec.exe"
    )
    foreach ($program in $guardedPrograms) {
        if (Test-Path -LiteralPath $program) {
            $programName = [IO.Path]::GetFileNameWithoutExtension($program)
            New-NetFirewallRule `
                -DisplayName "Marvin Test Forge - Block private networks - $programName" `
                -Direction Outbound -Action Block -Program $program `
                -RemoteAddress $privateRanges | Out-Null
        }
    }
    Add-Step -Name 'windows_network_guard' -Passed $true -ExitCode 0 `
        -Detail 'Internet autorise; reseaux prives bloques pour les processus de test.'

    $parseErrors = @()
    Get-ChildItem -LiteralPath 'C:\Marvin\Input' -Recurse -File |
        Where-Object { $_.Extension -in '.ps1', '.psm1' } |
        ForEach-Object {
            $tokens = $null
            $errors = $null
            [System.Management.Automation.Language.Parser]::ParseFile(
                $_.FullName, [ref]$tokens, [ref]$errors
            ) | Out-Null
            $parseErrors += @($errors)
        }
    if ($parseErrors.Count -gt 0) {
        throw (($parseErrors | ForEach-Object Message) -join [Environment]::NewLine)
    }
    Add-Step -Name 'powershell_parser_vm' -Passed $true -ExitCode 0 -Detail 'Syntaxe valide.'

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 `
        -Force -ForceBootstrap -Scope CurrentUser -Confirm:$false | Out-Null
    Import-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force | Out-Null
    Set-PSRepository -Name PSGallery -InstallationPolicy Trusted
    Install-Module PSScriptAnalyzer -RequiredVersion 1.25.0 -Scope CurrentUser `
        -Force -AllowClobber -SkipPublisherCheck -Confirm:$false
    Install-Module Pester -RequiredVersion 5.8.0 -Scope CurrentUser `
        -Force -AllowClobber -SkipPublisherCheck -Confirm:$false
    Add-Step -Name 'windows_dependencies' -Passed $true -ExitCode 0 `
        -Detail 'PSScriptAnalyzer 1.25.0 et Pester 5.8.0 installés depuis PSGallery.'

    $findings = Invoke-ScriptAnalyzer -Path 'C:\Marvin\Input' -Recurse -Severity Error,Warning
    if (@($findings).Count -gt 0) {
        throw (($findings | ForEach-Object { "$($_.RuleName): $($_.Message)" }) -join [Environment]::NewLine)
    }
    Add-Step -Name 'psscriptanalyzer_vm' -Passed $true -ExitCode 0 -Detail 'Aucun constat Error/Warning.'

    if (-not (Test-Path -LiteralPath 'C:\Marvin\Input\main.Tests.ps1')) {
        throw 'Une suite Pester est obligatoire pour le statut production.'
    }
    $pester = Invoke-Pester -Path 'C:\Marvin\Input\main.Tests.ps1' -PassThru -Output None
    $result.tests_executed = $true
    if ($pester.FailedCount -gt 0) {
        throw "Pester : $($pester.FailedCount) test(s) échoué(s) sur $($pester.TotalCount)."
    }
    Add-Step -Name 'pester_vm' -Passed $true -ExitCode 0 `
        -Detail "Pester : $($pester.PassedCount)/$($pester.TotalCount) tests réussis."
    $result.success = $true
    $result.production_ready = $true
}
catch {
    Add-Step -Name 'windows_execution_error' -Passed $false -ExitCode 1 -Detail $_.Exception.Message
    $result.error = $_.Exception.Message
}
finally {
    $result | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath 'C:\Marvin\Output\result.json' -Encoding UTF8
    Stop-Computer -Force
}
"""


def build_wsb(input_directory: Path, output_directory: Path) -> str:
    input_path = html.escape(str(input_directory.resolve()))
    output_path = html.escape(str(output_directory.resolve()))
    return rf"""<Configuration>
  <VGpu>Disable</VGpu>
  <Networking>Enable</Networking>
  <AudioInput>Disable</AudioInput>
  <VideoInput>Disable</VideoInput>
  <PrinterRedirection>Disable</PrinterRedirection>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <ProtectedClient>Enable</ProtectedClient>
  <MemoryInMB>4096</MemoryInMB>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>{input_path}</HostFolder>
      <SandboxFolder>C:\Marvin\Input</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>{output_path}</HostFolder>
      <SandboxFolder>C:\Marvin\Output</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Marvin\Input\bootstrap.ps1</Command>
  </LogonCommand>
</Configuration>
"""


def execute_powershell(
    code: str,
    test_code: str,
    *,
    files: dict[str, str] | None = None,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    run_id = "windows-forge-" + uuid.uuid4().hex[:12]
    runner_status = status()
    if not runner_status["available"]:
        return {
            "success": False,
            "production_ready": False,
            "run_id": run_id,
            "language": "powershell",
            "error": runner_status["error"],
            "steps": [],
            "tests_executed": False,
            "isolation": runner_status,
        }
    if not test_code.strip():
        return {
            "success": False,
            "production_ready": False,
            "run_id": run_id,
            "language": "powershell",
            "error": "Une suite Pester est obligatoire.",
            "steps": [],
            "tests_executed": False,
            "isolation": runner_status,
        }
    existing_process_ids = _sandbox_process_ids()
    if existing_process_ids:
        return {
            "success": False,
            "production_ready": False,
            "run_id": run_id,
            "language": "powershell",
            "error": "Une instance Windows Sandbox est deja ouverte. Fermez-la avant Test Forge.",
            "steps": [],
            "tests_executed": False,
            "isolation": runner_status,
        }
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(
        prefix="marvin-windows-forge-",
        ignore_cleanup_errors=True,
    ) as temporary:
        root = Path(temporary)
        input_directory = root / "input"
        output_directory = root / "output"
        input_directory.mkdir()
        output_directory.mkdir()
        (input_directory / "main.ps1").write_text(code, encoding="utf-8-sig")
        (input_directory / "main.Tests.ps1").write_text(test_code, encoding="utf-8-sig")
        (input_directory / "bootstrap.ps1").write_text(_bootstrap_script(), encoding="utf-8-sig")
        for raw_path, content in dict(files or {}).items():
            path = deliverable_bundle.normalize_path(raw_path)
            if path.casefold() in {"main.ps1", "main.tests.ps1", "bootstrap.ps1"}:
                continue
            destination = input_directory / Path(path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(str(content), encoding="utf-8-sig")
        wsb_path = root / "marvin-test-forge.wsb"
        wsb_path.write_text(build_wsb(input_directory, output_directory), encoding="utf-8")
        process = subprocess.Popen(
            [str(runner_status["executable"]), str(wsb_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        owned_process_ids: set[int] = set()
        result_path = output_directory / "result.json"
        deadline = time.monotonic() + max(120, min(int(timeout_seconds), 1800))
        while time.monotonic() < deadline:
            owned_process_ids.update(_sandbox_process_ids() - existing_process_ids)
            if result_path.exists():
                try:
                    payload = json.loads(result_path.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.5)
                    continue
                payload.update({
                    "run_id": run_id,
                    "language": "powershell",
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "isolation": runner_status,
                })
                payload["failed_steps"] = [
                    step.get("name")
                    for step in payload.get("steps", [])
                    if not step.get("passed")
                ]
                _wait_for_sandbox_exit(owned_process_ids)
                still_running = owned_process_ids.intersection(_sandbox_process_ids())
                if still_running:
                    _stop_owned_sandbox_processes(still_running)
                    _wait_for_sandbox_exit(still_running, timeout_seconds=10)
                return payload
            time.sleep(0.5)
        if process.poll() is None:
            process.terminate()
        owned_process_ids.update(_sandbox_process_ids() - existing_process_ids)
        _stop_owned_sandbox_processes(owned_process_ids)
        _wait_for_sandbox_exit(owned_process_ids, timeout_seconds=10)
        return {
            "success": False,
            "production_ready": False,
            "run_id": run_id,
            "language": "powershell",
            "error": "Windows Sandbox n'a pas produit de résultat avant le timeout.",
            "steps": [],
            "tests_executed": False,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "launcher_exit_code": process.poll(),
            "sandbox_process_ids": sorted(owned_process_ids),
            "isolation": runner_status,
        }
