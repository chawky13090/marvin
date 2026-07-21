"""Native Debian Test Forge runner backed by a clean Hyper-V checkpoint."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Final

import deliverable_bundle
import dpapi_secret_store
from config import DATA_DIR


VM_NAME: Final[str] = "Marvin-Debian13-TestForge"
CHECKPOINT_NAME: Final[str] = "Marvin-Clean"
USERNAME: Final[str] = "marvin"
KEY_SECRET: Final[str] = "vm_lab.debian13.ssh_private_key"
RUNNER_PATH: Final[str] = "/usr/local/sbin/marvin-test-forge-runner"
STATE_PATH = Path(DATA_DIR) / "linux_test_forge_session.json"
INSTALL_RESULT_PATH = Path(DATA_DIR) / "debian-vm-install-result.json"
_RUN_ID = re.compile(r"^linux-forge-[a-f0-9]{12}$")
_EXECUTION_LOCK = threading.Lock()


class LinuxRunnerError(RuntimeError):
    pass


def _powershell(script: str, *, input_text: str = "", timeout: int = 30) -> subprocess.CompletedProcess[str]:
    executable = os.environ.get("SystemRoot", r"C:\Windows") + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
    return subprocess.run(
        [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        input=input_text, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=False,
    )


def _read_state() -> dict[str, Any]:
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(value: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, STATE_PATH)


_STATUS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Import-Module Hyper-V
$vm = Get-VM -Name 'Marvin-Debian13-TestForge' -ErrorAction Stop
$clean = Get-VMCheckpoint -VMName $vm.Name -Name 'Marvin-Clean' -ErrorAction Stop
$results = @(Get-VMCheckpoint -VMName $vm.Name -ErrorAction SilentlyContinue | Where-Object Name -Like 'Marvin-Result-*' | ForEach-Object Name)
[ordered]@{ hyperv_access=$true; vm_exists=$true; checkpoint_exists=($null -ne $clean); vm_state=[string]$vm.State; result_checkpoints=$results; switches=@(Get-VMNetworkAdapter -VMName $vm.Name | ForEach-Object SwitchName) } | ConvertTo-Json -Compress
"""


def status() -> dict[str, Any]:
    state = _read_state()
    try:
        installation = json.loads(INSTALL_RESULT_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        installation = {}
    harness_ready = installation.get("native_runner_version") == 1
    base = {
        "backend": "hyperv_debian_ssh", "vm_name": VM_NAME,
        "checkpoint_name": CHECKPOINT_NAME, "guest_username": USERNAME,
        "credential_present": dpapi_secret_store.has_secret(KEY_SECRET),
        "runner_path": RUNNER_PATH, "ready": False, "error": None,
        "native_harness_ready": harness_ready,
        "result_session": state if state.get("status") in {"result_available", "manual_active"} else None,
    }
    try:
        completed = _powershell(_STATUS_SCRIPT, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        base["error"] = f"Inspection Hyper-V impossible : {exc}"
        return base
    if completed.returncode:
        base["error"] = (completed.stderr or completed.stdout).strip()[:1_500] or "VM Debian indisponible."
        return base
    try:
        base.update(json.loads(completed.stdout.strip().splitlines()[-1]))
    except (IndexError, TypeError, json.JSONDecodeError):
        base["error"] = "Réponse Hyper-V Debian invalide."
        return base
    manual_active = state.get("status") == "manual_active"
    base["ready"] = bool(
        base.get("checkpoint_exists") and base.get("credential_present")
        and harness_ready and not manual_active
    )
    if not base["ready"]:
        base["error"] = (
            "La VM est conservée pour un test manuel; restaurez la base saine avant une nouvelle validation."
            if manual_active else (
                "La VM Debian doit être reprovisionnée une fois pour installer le harnais Test Forge natif."
                if not harness_ready else "VM, checkpoint propre ou clé SSH DPAPI manquant."
            )
        )
    return base


_ORCHESTRATOR = r"""
$ErrorActionPreference = 'Stop'
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
Import-Module Hyper-V
$vm = Get-VM -Name ([string]$payload.vm_name) -ErrorAction Stop
$restoredBefore = $false; $restoredAfter = $false; $resultCheckpoint = $null
$hostError = $null; $stdout = ''; $stderr = ''; $exitCode = -1
try {
  if ($vm.State -ne 'Off') { Stop-VM -VM $vm -TurnOff -Force }
  Restore-VMCheckpoint -VMName $vm.Name -Name ([string]$payload.checkpoint_name) -Confirm:$false
  $restoredBefore = $true
  $adapters = @(Get-VMNetworkAdapter -VMName $vm.Name)
  if (-not @($adapters | Where-Object SwitchName).Count) { $adapters | Select-Object -First 1 | Connect-VMNetworkAdapter -SwitchName 'Default Switch' }
  Start-VM -VM $vm | Out-Null
  $deadline = [DateTime]::UtcNow.AddSeconds(150); $ip = $null
  do { Start-Sleep -Seconds 2; $ip = @(Get-VMNetworkAdapter -VMName $vm.Name | ForEach-Object IPAddresses | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' -and $_ -notlike '169.254.*' }) | Select-Object -First 1 } until ($ip -or [DateTime]::UtcNow -gt $deadline)
  if (-not $ip) { throw 'La VM Debian n a pas obtenu d adresse IPv4.' }
  $ssh = @('-i',[string]$payload.key_path,'-o','BatchMode=yes','-o','ConnectTimeout=15','-o','StrictHostKeyChecking=accept-new','-o',('UserKnownHostsFile=' + [string]$payload.known_hosts))
  $remote = ([string]$payload.username) + '@' + $ip
  $remoteRoot = '/var/tmp/' + [string]$payload.run_id
  & ssh.exe @ssh $remote ('install -d -m 0700 ' + $remoteRoot)
  if ($LASTEXITCODE -ne 0) { throw 'Création du répertoire de test Debian échouée.' }
  $sources = @(Get-ChildItem -LiteralPath ([string]$payload.input_path) -Force | ForEach-Object FullName)
  if (-not $sources.Count) { throw 'Le bundle Debian local est vide.' }
  & scp.exe @ssh -r @sources ($remote + ':' + $remoteRoot + '/')
  if ($LASTEXITCODE -ne 0) { throw 'Copie SCP vers Debian échouée.' }
  # Windows PowerShell 5 transforme les lignes stderr d'un programme natif en
  # ErrorRecord. Avec ErrorActionPreference=Stop, un simple avertissement du
  # livrable interrompait l'orchestrateur avant la lecture de LASTEXITCODE.
  # Le code de sortie SSH et le marqueur structuré restent les seules preuves
  # de succès; stderr est conservé dans le rapport sans devenir une exception hôte.
  $previousErrorPreference = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $output = & ssh.exe @ssh $remote ('sudo ' + [string]$payload.runner_path + ' ' + [string]$payload.run_id) 2>&1
    $exitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $previousErrorPreference
  }
  $stdout = ($output -join "`n")
  if ($exitCode -ne 0) { $stderr = $stdout }
  if ($exitCode -eq 0 -and $payload.capture_result) {
    & ssh.exe @ssh $remote 'sudo /usr/bin/systemctl poweroff' | Out-Null
    $deadline = [DateTime]::UtcNow.AddSeconds(120)
    do { Start-Sleep -Seconds 2; $vm = Get-VM -Name $vm.Name } until ($vm.State -eq 'Off' -or [DateTime]::UtcNow -gt $deadline)
    if ($vm.State -ne 'Off') { Stop-VM -VM $vm -TurnOff -Force }
    Get-VMCheckpoint -VMName $vm.Name -ErrorAction SilentlyContinue | Where-Object Name -Like 'Marvin-Result-*' | Remove-VMCheckpoint -Confirm:$false -ErrorAction SilentlyContinue
    $resultCheckpoint = 'Marvin-Result-' + [string]$payload.run_id
    Checkpoint-VM -VMName $vm.Name -SnapshotName $resultCheckpoint | Out-Null
  }
} catch { $hostError = $_.Exception.Message }
finally {
  $vm = Get-VM -Name ([string]$payload.vm_name) -ErrorAction SilentlyContinue
  if ($vm -and $vm.State -ne 'Off') { Stop-VM -VM $vm -TurnOff -Force -ErrorAction SilentlyContinue }
  if ($vm) { try { Restore-VMCheckpoint -VMName $vm.Name -Name ([string]$payload.checkpoint_name) -Confirm:$false -ErrorAction Stop; $restoredAfter = $true } catch { $restoredAfter = $false } }
}
if ($hostError) { throw $hostError }
[ordered]@{ exit_code=$exitCode; stdout=$stdout; stderr=$stderr; checkpoint_restored_before=$restoredBefore; checkpoint_restored_after=$restoredAfter; result_checkpoint=$resultCheckpoint; network_used_for_guest=$true; host_network_modified=$false } | ConvertTo-Json -Depth 6 -Compress
"""


def _execute(files: dict[str, str], *, timeout_seconds: int = 1_800, capture_result: bool = True) -> dict[str, Any]:
    runner = status()
    if not runner["ready"]:
        return {"success": False, "production_ready": False, "tests_executed": False,
                "error": runner["error"], "steps": [], "isolation": runner}
    try:
        normalized_names = {
            deliverable_bundle.normalize_path(path): str(content)
            for path, content in files.items()
        }
    except deliverable_bundle.BundleError as exc:
        raise LinuxRunnerError(str(exc)) from exc
    required = {"main.sh", "integration.sh", "test_main.bats"}
    missing = sorted(required.difference(normalized_names))
    if missing:
        return {
            "success": False, "production_ready": False, "tests_executed": False,
            "error": "Bundle Debian incomplet : " + ", ".join(missing),
            "steps": [], "isolation": runner,
        }
    run_id = "linux-forge-" + uuid.uuid4().hex[:12]
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="marvin-linux-forge-") as temporary:
        root = Path(temporary); input_directory = root / "input"; input_directory.mkdir()
        for relative, content in normalized_names.items():
            destination = input_directory / Path(relative); destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(str(content), encoding="utf-8", newline="\n")
        (input_directory / "run.sh").write_text(
            '#!/usr/bin/env bash\nset -Eeuo pipefail\ncd "$(dirname "$0")"\nchmod +x ./main.sh ./integration.sh 2>/dev/null || true\nbash ./integration.sh\nbats --formatter tap ./test_main.bats\nprintf "%s\\n" "MARVIN_NATIVE_LINUX_COMPLETE=full"\n',
            encoding="utf-8", newline="\n",
        )
        key_path = root / "id_ed25519"; key = dpapi_secret_store.get_secret(KEY_SECRET)
        if not key:
            raise LinuxRunnerError("Clé SSH Debian DPAPI absente.")
        key_path.write_text(key, encoding="ascii", newline="\n")
        subprocess.run(["icacls.exe", str(key_path), "/inheritance:r", "/grant:r", f"{os.environ.get('USERNAME', '')}:F"], capture_output=True, check=False)
        payload = {"vm_name": VM_NAME, "checkpoint_name": CHECKPOINT_NAME, "username": USERNAME,
                   "runner_path": RUNNER_PATH, "run_id": run_id, "input_path": str(input_directory),
                   "key_path": str(key_path), "known_hosts": str(root / "known_hosts"), "capture_result": bool(capture_result)}
        completed = _powershell(_ORCHESTRATOR, input_text=json.dumps(payload, ensure_ascii=False), timeout=max(300, min(int(timeout_seconds), 7_200)))
    if completed.returncode:
        return {"success": False, "production_ready": False, "tests_executed": False,
                "error": (completed.stderr or completed.stdout).strip()[:4_000], "run_id": run_id, "steps": [], "isolation": runner}
    try:
        envelope = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, TypeError, json.JSONDecodeError):
        return {"success": False, "production_ready": False, "tests_executed": False,
                "error": "Le runner Debian n'a pas retourné de preuve JSON valide.", "run_id": run_id, "steps": [], "isolation": runner}
    output = str(envelope.get("stdout") or ""); marker = "MARVIN_NATIVE_LINUX_COMPLETE=full" in output
    success = envelope.get("exit_code") == 0 and marker; result_checkpoint = envelope.get("result_checkpoint")
    if success and result_checkpoint:
        _write_state({"status": "result_available", "run_id": run_id, "checkpoint": result_checkpoint, "created_at": time.time()})
    restored = bool(envelope.get("checkpoint_restored_before") and envelope.get("checkpoint_restored_after"))
    step = {"name": "native_debian_vm", "passed": bool(success and restored), "exit_code": int(envelope.get("exit_code") or 0),
            "duration_ms": int((time.perf_counter() - started) * 1_000), "stdout": output[-20_000:],
            "stderr": str(envelope.get("stderr") or "")[-20_000:], "test_completion_marker": marker, "image": None}
    return {"success": bool(success and restored), "production_ready": bool(success and restored), "tests_executed": marker,
            "run_id": run_id, "steps": [step], "result_snapshot_available": bool(result_checkpoint),
            "isolation": {**runner, "checkpoint_restored_before": bool(envelope.get("checkpoint_restored_before")),
                          "checkpoint_restored_after": bool(envelope.get("checkpoint_restored_after")), "result_checkpoint": result_checkpoint,
                          "network": "guest_default_switch_during_test", "host_network_modified": False, "host_mount": False,
                          "secret_transport": "ssh_key_dpapi"}}


def execute(files: dict[str, str], *, timeout_seconds: int = 1_800, capture_result: bool = True) -> dict[str, Any]:
    if not _EXECUTION_LOCK.acquire(blocking=False):
        return {
            "success": False, "production_ready": False, "tests_executed": False,
            "error": "Une validation Debian est déjà en cours sur la VM Test Forge.",
            "steps": [], "isolation": status(),
        }
    try:
        return _execute(files, timeout_seconds=timeout_seconds, capture_result=capture_result)
    finally:
        _EXECUTION_LOCK.release()


_SESSION_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
Import-Module Hyper-V
$vm = Get-VM -Name 'Marvin-Debian13-TestForge' -ErrorAction Stop
if ($vm.State -ne 'Off') { Stop-VM -VM $vm -TurnOff -Force }
if ($payload.action -eq 'open') { Restore-VMCheckpoint -VMName $vm.Name -Name ([string]$payload.checkpoint) -Confirm:$false; Start-VM -VM $vm | Out-Null }
elseif ($payload.action -eq 'restore') { Restore-VMCheckpoint -VMName $vm.Name -Name 'Marvin-Clean' -Confirm:$false; Get-VMCheckpoint -VMName $vm.Name -ErrorAction SilentlyContinue | Where-Object Name -Like 'Marvin-Result-*' | Remove-VMCheckpoint -Confirm:$false }
else { throw 'Action de session inconnue.' }
[ordered]@{ success=$true; action=[string]$payload.action; vm_state=[string](Get-VM -Name $vm.Name).State } | ConvertTo-Json -Compress
"""


def open_result(*, run_id: str, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise LinuxRunnerError("L'ouverture de la VM de résultat doit être confirmée.")
    state = _read_state()
    if not _RUN_ID.fullmatch(run_id) or state.get("run_id") != run_id or not state.get("checkpoint"):
        raise LinuxRunnerError("Snapshot temporaire de résultat introuvable.")
    completed = _powershell(_SESSION_SCRIPT, input_text=json.dumps({"action": "open", "checkpoint": state["checkpoint"]}), timeout=180)
    if completed.returncode:
        raise LinuxRunnerError((completed.stderr or completed.stdout).strip()[:2_000])
    state.update({"status": "manual_active", "opened_at": time.time()}); _write_state(state)
    return {**json.loads(completed.stdout.strip().splitlines()[-1]), "session": state}


def restore_clean(*, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise LinuxRunnerError("La restauration de la base saine doit être confirmée.")
    completed = _powershell(_SESSION_SCRIPT, input_text=json.dumps({"action": "restore"}), timeout=180)
    if completed.returncode:
        raise LinuxRunnerError((completed.stderr or completed.stdout).strip()[:2_000])
    _write_state({"status": "clean", "restored_at": time.time()})
    return {**json.loads(completed.stdout.strip().splitlines()[-1]), "session": _read_state()}
