"""Persistent, single-flight VM Lab installation jobs launched by Marvin."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Final

import vm_lab
from config import DATA_DIR


ROOT: Final[Path] = Path(__file__).resolve().parents[1]
STATE_PATH: Final[Path] = Path(DATA_DIR) / "vm_lab_install_job.json"
LOG_ROOT: Final[Path] = Path(DATA_DIR) / "vm_lab_jobs"
_RESULTS: Final[dict[str, Path]] = {
    "debian13": Path(DATA_DIR) / "debian-vm-install-result.json",
    "windows11": Path(DATA_DIR) / "windows-vm-install-result.json",
}
_LOCK = threading.RLock()
_PROCESSES: dict[str, subprocess.Popen[str]] = {}


class VMLabJobError(RuntimeError):
    pass


def _read_state() -> dict[str, Any]:
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(value: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, STATE_PATH)


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    process = _PROCESSES.get(str(pid))
    if process is not None:
        return process.poll() is None
    try:
        observed = subprocess.run(
            ["tasklist.exe", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return observed.returncode == 0 and str(pid) in observed.stdout and "INFO:" not in observed.stdout


def _tail(path: Path, limit: int = 12_000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", errors="replace")


def _result_after_start(profile: str, started_at: float) -> dict[str, Any] | None:
    path = _RESULTS[profile]
    try:
        if path.stat().st_mtime + 1 < started_at:
            return None
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _reconcile(state: dict[str, Any]) -> dict[str, Any]:
    if not state or state.get("status") not in {"queued", "running"}:
        return state
    pid = int(state.get("pid") or 0)
    if _pid_is_running(pid):
        if state.get("status") != "running":
            state["status"] = "running"
            _write_state(state)
        return state
    result = _result_after_start(str(state["profile"]), float(state["started_at"]))
    state["finished_at"] = time.time()
    state["result"] = result
    state["status"] = "completed" if result and result.get("status") == "completed" else "failed"
    if not result:
        state["error"] = "Le processus s est arrêté sans preuve d installation exploitable."
    elif result.get("status") != "completed":
        state["error"] = str(result.get("error") or "Installation VM Lab échouée.")
    _write_state(state)
    return state


def status() -> dict[str, Any]:
    with _LOCK:
        state = _reconcile(_read_state())
        if not state:
            return {"status": "idle", "active": False}
        public = dict(state)
        public["active"] = public.get("status") in {"queued", "running"}
        public["log_tail"] = _tail(Path(str(public.get("log_path") or "")))
        return public


def _watch(job_id: str, process: subprocess.Popen[str], log_stream) -> None:
    try:
        process.wait()
    finally:
        log_stream.close()
        with _LOCK:
            state = _read_state()
            if state.get("job_id") == job_id:
                _reconcile(state)
            _PROCESSES.pop(str(process.pid), None)


def start(profile: str, *, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise VMLabJobError("La recréation de la VM doit être confirmée explicitement.")
    profile = str(profile or "").strip().casefold()
    if profile not in vm_lab.PROFILES:
        raise VMLabJobError("Profil VM Lab inconnu.")
    with _LOCK:
        current = _reconcile(_read_state())
        if current.get("status") in {"queued", "running"}:
            raise VMLabJobError(f"Une installation VM Lab est déjà active ({current.get('job_id')}).")
        lab = vm_lab.status()
        selected = next(item for item in lab["profiles"] if item["id"] == profile)
        if not lab["hyperv"].get("access"):
            raise VMLabJobError(str(lab["hyperv"].get("error") or "Accès Hyper-V indisponible."))
        if not lab.get("installation_switch"):
            raise VMLabJobError("Le commutateur Hyper-V Default Switch est indisponible.")
        if not selected.get("iso_verified"):
            raise VMLabJobError("L ISO doit être présente et vérifiée avant l installation.")
        if not selected.get("capacity_ready"):
            raise VMLabJobError("Espace disque insuffisant pour ce profil VM Lab.")

        job_id = "vm-lab-" + uuid.uuid4().hex[:12]
        LOG_ROOT.mkdir(parents=True, exist_ok=True)
        log_path = LOG_ROOT / f"{job_id}.log"
        log_stream = log_path.open("w", encoding="utf-8", errors="replace")
        executable = os.environ.get("SystemRoot", r"C:\Windows") + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
        command = [
            executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(ROOT / "scripts" / "run-vm-lab-install.ps1"),
            "-Profile", profile, "-Confirmed",
        ]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            process = subprocess.Popen(
                command, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log_stream,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                creationflags=creation_flags,
            )
        except OSError:
            log_stream.close()
            raise
        state = {
            "job_id": job_id, "profile": profile, "status": "running", "pid": process.pid,
            "started_at": time.time(), "log_path": str(log_path),
            "destructive_scope": f"recreate:{vm_lab.PROFILES[profile]['vm_name']}",
            "host_network_policy": lab["host_network_policy"],
        }
        _write_state(state)
        _PROCESSES[str(process.pid)] = process
        threading.Thread(target=_watch, args=(job_id, process, log_stream), daemon=True).start()
        return status()
