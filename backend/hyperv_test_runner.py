"""Native Windows headless runner using Hyper-V checkpoints and PowerShell Direct."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import deliverable_bundle
import dpapi_secret_store
from config import DATA_DIR


CONFIG_PATH = Path(DATA_DIR) / "hyperv_test_forge.json"
PASSWORD_KEY = "vm_lab.windows11.guest_password"
_NAME = re.compile(r"^[^\x00-\x1f<>|]{1,100}$")


class HyperVRunnerError(RuntimeError):
    pass


def _load_config() -> dict[str, Any]:
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_config(value: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, CONFIG_PATH)


def configure(*, vm_name: str, checkpoint_name: str, guest_username: str,
              guest_password: str, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise HyperVRunnerError("La configuration du runner doit être confirmée explicitement.")
    for label, value in (("VM", vm_name), ("checkpoint", checkpoint_name), ("compte invité", guest_username)):
        if not _NAME.fullmatch(str(value).strip()):
            raise HyperVRunnerError(f"Nom {label} invalide.")
    dpapi_secret_store.set_secret(PASSWORD_KEY, guest_password)
    config = {
        "vm_name": vm_name.strip(),
        "checkpoint_name": checkpoint_name.strip(),
        "guest_username": guest_username.strip(),
        "network_mode": "offline_native_execution",
        "configured_at": time.time(),
    }
    _write_config(config)
    return status()


def configure_from_stored_secret(*, vm_name: str, checkpoint_name: str,
                                 guest_username: str, confirmed: bool) -> dict[str, Any]:
    """Bind an already provisioned VM without moving its secret through an API payload."""
    if not confirmed:
        raise HyperVRunnerError("La configuration du runner doit être confirmée explicitement.")
    if not dpapi_secret_store.has_secret(PASSWORD_KEY):
        raise HyperVRunnerError("Secret invité DPAPI absent.")
    for label, value in (("VM", vm_name), ("checkpoint", checkpoint_name),
                         ("compte invité", guest_username)):
        if not _NAME.fullmatch(str(value).strip()):
            raise HyperVRunnerError(f"Nom {label} invalide.")
    _write_config({
        "vm_name": vm_name.strip(), "checkpoint_name": checkpoint_name.strip(),
        "guest_username": guest_username.strip(), "network_mode": "offline_native_execution",
        "configured_at": time.time(), "credential_source": "vm_lab_dpapi",
    })
    return status()


def _powershell(script: str, *, input_text: str = "", timeout: int = 30) -> subprocess.CompletedProcess[str]:
    executable = os.environ.get("SystemRoot", r"C:\Windows") + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
    return subprocess.run(
        [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        input=input_text, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=False,
    )


def status() -> dict[str, Any]:
    config = _load_config()
    base = {
        "backend": "hyperv_powershell_direct",
        "configured": bool(config),
        "vm_name": config.get("vm_name"),
        "checkpoint_name": config.get("checkpoint_name"),
        "guest_username": config.get("guest_username"),
        "credential_present": dpapi_secret_store.has_secret(PASSWORD_KEY),
        "network_mode": "offline_native_execution",
        "vm_exists": False, "checkpoint_exists": False, "hyperv_access": False,
        "ready": False, "error": None,
    }
    if not config:
        base["error"] = "Aucune VM Test Forge Hyper-V configurée."
        return base
    script = r"""
$ErrorActionPreference = 'Stop'
Import-Module Hyper-V
$vm = Get-VM -Name $env:MARVIN_VM_NAME
$checkpoint = Get-VMCheckpoint -VMName $vm.Name -Name $env:MARVIN_CHECKPOINT_NAME -ErrorAction Stop
$os = Get-CimInstance Win32_OperatingSystem
[ordered]@{
  hyperv_access = $true
  vm_exists = ($null -ne $vm)
  checkpoint_exists = ($null -ne $checkpoint)
  vm_state = [string]$vm.State
  generation = $vm.Generation
  checkpoint_type = [string]$vm.CheckpointType
  switches = @((Get-VMNetworkAdapter -VMName $vm.Name | ForEach-Object SwitchName))
  host_free_memory_bytes = ([int64]$os.FreePhysicalMemory * 1KB)
  memory_startup_bytes = [int64]$vm.MemoryStartup
} | ConvertTo-Json -Compress
"""
    env = os.environ.copy()
    env["MARVIN_VM_NAME"] = str(config["vm_name"])
    env["MARVIN_CHECKPOINT_NAME"] = str(config["checkpoint_name"])
    executable = env.get("SystemRoot", r"C:\Windows") + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
    try:
        result = subprocess.run(
            [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
            check=False, env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        base["error"] = f"Inspection Hyper-V impossible : {exc}"
        return base
    if result.returncode:
        base["error"] = (result.stderr or result.stdout).strip()[:1_000] or "Accès Hyper-V refusé."
        return base
    try:
        observed = json.loads(result.stdout.strip())
    except (TypeError, json.JSONDecodeError):
        base["error"] = "Réponse Hyper-V invalide."
        return base
    base.update(observed)
    memory_ready = (
        str(base.get("vm_state") or "").casefold() != "off"
        or int(base.get("host_free_memory_bytes") or 0)
        >= int(base.get("memory_startup_bytes") or 0)
    )
    base["memory_ready"] = memory_ready
    base["ready"] = bool(
        base["hyperv_access"] and base["vm_exists"] and base["checkpoint_exists"]
        and base["credential_present"] and memory_ready
    )
    if not base["ready"]:
        base["error"] = (
            "Mémoire hôte insuffisante pour démarrer la VM Windows; libérez le modèle local ou attendez sa décharge."
            if not memory_ready
            else "VM, checkpoint ou secret invité manquant."
        )
    return base


_ORCHESTRATOR = r"""
$ErrorActionPreference = 'Stop'
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$secure = ConvertTo-SecureString ([string]$payload.password) -AsPlainText -Force
$credential = [PSCredential]::new([string]$payload.username, $secure)
$payload.password = $null
$session = $null
$switches = @()
$restoredBefore = $false
$restoredAfter = $false
$guestResult = $null
$hostError = $null
try {
  $vm = Get-VM -Name ([string]$payload.vm_name) -ErrorAction Stop
  if ($vm.State -ne 'Off') { Stop-VM -VM $vm -TurnOff -Force }
  Restore-VMCheckpoint -VMName $vm.Name -Name ([string]$payload.checkpoint_name) -Confirm:$false
  $restoredBefore = $true
  $switches = @(Get-VMNetworkAdapter -VMName $vm.Name | ForEach-Object SwitchName | Where-Object { $_ })
  Get-VMNetworkAdapter -VMName $vm.Name | Disconnect-VMNetworkAdapter
  Start-VM -VM $vm | Out-Null
  $deadline = [DateTime]::UtcNow.AddSeconds(120)
  do {
    try { $session = New-PSSession -VMName $vm.Name -Credential $credential -ErrorAction Stop } catch { Start-Sleep -Seconds 2 }
  } until ($session -or [DateTime]::UtcNow -gt $deadline)
  if (-not $session) { throw 'PowerShell Direct indisponible après 120 secondes.' }
  $guestRoot = 'C:\Marvin\TestRun'
  Invoke-Command -Session $session -ScriptBlock { param($p) Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Path $p -Force | Out-Null } -ArgumentList $guestRoot
  Copy-Item -Path (([string]$payload.input_path) + '\*') -Destination $guestRoot -Recurse -ToSession $session -Force
  $guestResult = Invoke-Command -Session $session -ScriptBlock {
    param($root)
    $manifest = Get-Content -LiteralPath (Join-Path $root 'marvin-run.json') -Raw | ConvertFrom-Json
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $steps = @()
    foreach ($item in @($manifest.commands)) {
      $psi = New-Object Diagnostics.ProcessStartInfo
      $psi.FileName = "$env:SystemRoot\System32\cmd.exe"
      $psi.Arguments = '/d /s /c "' + ([string]$item.command).Replace('"','\"') + '"'
      $psi.WorkingDirectory = $root
      $psi.UseShellExecute = $false
      $psi.RedirectStandardOutput = $true
      $psi.RedirectStandardError = $true
      $process = [Diagnostics.Process]::Start($psi)
      $finished = $process.WaitForExit(([int]$item.timeout_seconds * 1000))
      if (-not $finished) { & taskkill.exe /PID $process.Id /T /F | Out-Null }
      $stdout = $process.StandardOutput.ReadToEnd()
      $stderr = $process.StandardError.ReadToEnd()
      $steps += [ordered]@{
        name = [string]$item.name; passed = ($finished -and $process.ExitCode -eq 0)
        exit_code = $(if ($finished) { $process.ExitCode } else { -1 }); timed_out = (-not $finished)
        stdout = $stdout.Substring(0, [Math]::Min($stdout.Length, 12000))
        stderr = $stderr.Substring(0, [Math]::Min($stderr.Length, 12000))
      }
      if (-not $steps[-1].passed) { break }
    }
    [ordered]@{
      success = (@($steps).Count -gt 0 -and @($steps | Where-Object { -not $_.passed }).Count -eq 0)
      tests_executed = (@($steps).Count -gt 0)
      guest_is_admin = $isAdmin
      steps = $steps
      os = [Environment]::OSVersion.VersionString
      powershell = $PSVersionTable.PSVersion.ToString()
    }
  } -ArgumentList $guestRoot
}
catch { $hostError = $_.Exception.Message }
finally {
  if ($session) { Remove-PSSession $session -ErrorAction SilentlyContinue }
  $vm = Get-VM -Name ([string]$payload.vm_name) -ErrorAction SilentlyContinue
  if ($vm -and $vm.State -ne 'Off') { Stop-VM -VM $vm -TurnOff -Force -ErrorAction SilentlyContinue }
  if ($vm) {
    try {
      Restore-VMCheckpoint -VMName $vm.Name -Name ([string]$payload.checkpoint_name) -Confirm:$false -ErrorAction Stop
      $restoredAfter = $true
    } catch { $restoredAfter = $false }
    foreach ($switch in $switches) { Get-VMNetworkAdapter -VMName $vm.Name | Where-Object { -not $_.SwitchName } | Select-Object -First 1 | Connect-VMNetworkAdapter -SwitchName $switch -ErrorAction SilentlyContinue }
  }
}
if ($hostError) { throw $hostError }
[ordered]@{
  guest = $guestResult
  checkpoint_restored_before = $restoredBefore
  checkpoint_restored_after = $restoredAfter
  network_disconnected_during_execution = $true
} | ConvertTo-Json -Depth 9 -Compress
"""


def execute(files: dict[str, str], commands: list[dict[str, Any]], *, confirmed: bool,
            timeout_seconds: int = 1_800) -> dict[str, Any]:
    if not confirmed:
        raise HyperVRunnerError("L'exécution Windows native doit être confirmée.")
    runner = status()
    if not runner["ready"]:
        return {"success": False, "production_ready": False, "tests_executed": False,
                "error": runner["error"], "isolation": runner, "steps": []}
    if not commands or len(commands) > 20:
        raise HyperVRunnerError("Entre une et vingt commandes de validation sont requises.")
    normalized_commands = []
    for index, item in enumerate(commands):
        command = str(item.get("command") or "")
        if not command or len(command) > 2_000 or "\x00" in command:
            raise HyperVRunnerError("Commande Windows vide ou trop longue.")
        normalized_commands.append({
            "name": str(item.get("name") or f"step_{index + 1}")[:100],
            "command": command,
            "timeout_seconds": max(5, min(int(item.get("timeout_seconds") or 300), 1_200)),
        })
    password = dpapi_secret_store.get_secret(PASSWORD_KEY)
    if not password:
        raise HyperVRunnerError("Secret invité DPAPI absent.")
    config = _load_config()
    started = time.perf_counter()
    run_id = "hyperv-forge-" + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="marvin-hyperv-forge-") as temporary:
        input_directory = Path(temporary) / "input"
        input_directory.mkdir()
        for raw_path, content in files.items():
            try:
                relative = deliverable_bundle.normalize_path(raw_path)
            except deliverable_bundle.BundleError as exc:
                raise HyperVRunnerError(str(exc)) from exc
            destination = input_directory / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(str(content), encoding="utf-8")
        (input_directory / "marvin-run.json").write_text(
            json.dumps({"commands": normalized_commands}, ensure_ascii=False), encoding="utf-8",
        )
        payload = {
            "vm_name": config["vm_name"], "checkpoint_name": config["checkpoint_name"],
            "username": config["guest_username"], "password": password,
            "input_path": str(input_directory.resolve()),
        }
        try:
            completed = _powershell(
                _ORCHESTRATOR, input_text=json.dumps(payload, ensure_ascii=False),
                timeout=max(180, min(int(timeout_seconds), 7_200)),
            )
        finally:
            payload["password"] = None
            password = ""
    if completed.returncode:
        return {"success": False, "production_ready": False, "tests_executed": False,
                "error": (completed.stderr or completed.stdout).strip()[:2_000],
                "run_id": run_id, "steps": [], "isolation": runner}
    try:
        envelope = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, TypeError, json.JSONDecodeError):
        return {"success": False, "production_ready": False, "tests_executed": False,
                "error": "Le runner Hyper-V n'a pas retourné de preuve JSON valide.",
                "run_id": run_id, "steps": [], "isolation": runner}
    result = dict(envelope.get("guest") or {})
    result.update({
        "run_id": run_id, "duration_ms": int((time.perf_counter() - started) * 1_000),
        "isolation": {**runner, "network_disconnected_during_execution": True,
                      "input_transport": "powershell_direct",
                      "checkpoint_restored_before": bool(envelope.get("checkpoint_restored_before")),
                      "checkpoint_restored_after": bool(envelope.get("checkpoint_restored_after"))},
    })
    result["production_ready"] = bool(
        result.get("success") and result.get("tests_executed")
        and not result.get("guest_is_admin")
        and envelope.get("checkpoint_restored_before") and envelope.get("checkpoint_restored_after")
        and envelope.get("network_disconnected_during_execution")
    )
    return result


def commands_for(language: str, files: dict[str, str]) -> list[dict[str, Any]]:
    """Return deterministic native checks; no project-provided shell text is inferred."""
    normalized = str(language or "").casefold()
    names = {str(path).replace("\\", "/") for path in files}
    if normalized == "python":
        discovery = (
            "python -m unittest discover -s tests -v"
            if any(name.startswith("tests/") for name in names)
            else "python -m unittest discover -v"
        )
        unittest_command = discovery
        if any(name.startswith("src/") for name in names):
            # Les projets Python modernes utilisent souvent un src-layout. La VM
            # reçoit le livrable brut, sans installation préalable : rendre ce
            # dossier importable est donc une responsabilité du harness natif.
            unittest_command = (
                "set PYTHONPATH=%CD%\\src;%PYTHONPATH%"
                f" && {discovery}"
            )
        return [
            {"name": "python_compile_windows", "command": "python -m compileall -q .", "timeout_seconds": 180},
            {"name": "python_unittest_windows", "command": unittest_command, "timeout_seconds": 600},
        ]
    if normalized in {"javascript", "typescript"}:
        commands = []
        primary = next((name for name in ("main.mjs", "main.js", "index.js") if name in names), None)
        if primary:
            commands.append({"name": "node_check_windows", "command": f"node --check {primary}", "timeout_seconds": 120})
        if "package.json" in names:
            commands.append({"name": "npm_test_windows", "command": "npm test", "timeout_seconds": 900})
        return commands
    if normalized == "go":
        return [{"name": "go_test_windows", "command": "go test ./...", "timeout_seconds": 900}]
    if normalized == "csharp":
        return [{"name": "dotnet_test_windows", "command": "dotnet test --nologo", "timeout_seconds": 1_200}]
    if normalized == "rust":
        return [{"name": "cargo_test_windows", "command": "cargo test --locked", "timeout_seconds": 1_200}]
    if normalized == "java":
        if "mvnw.cmd" in names:
            return [{"name": "maven_test_windows", "command": "mvnw.cmd test", "timeout_seconds": 1_200}]
        if "gradlew.bat" in names:
            return [{"name": "gradle_test_windows", "command": "gradlew.bat test", "timeout_seconds": 1_200}]
    return []
