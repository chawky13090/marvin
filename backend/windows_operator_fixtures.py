"""Fixtures et oracles indépendants du futur opérateur Windows Forge."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil

from config import DATA_DIR


FIXTURE_ROOT = (DATA_DIR / "forge" / "benchmark-fixtures").resolve()


def _process_ids(name: str) -> set[int]:
    expected = name.casefold().removesuffix(".exe")
    result: set[int] = set()
    for process in psutil.process_iter(("pid", "name")):
        try:
            current = str(process.info.get("name") or "").casefold().removesuffix(".exe")
            if current == expected:
                result.add(int(process.info["pid"]))
        except (psutil.Error, TypeError, ValueError):
            continue
    return result


def _run_root(run_id: str) -> Path:
    safe = "".join(char for char in str(run_id) if char.isalnum() or char in "-_")[:80]
    if not safe:
        raise ValueError("Identifiant de répétition invalide.")
    root = (FIXTURE_ROOT / safe).resolve()
    if FIXTURE_ROOT not in root.parents:
        raise ValueError("Fixture hors racine Forge.")
    return root


def setup(fixture_id: str, *, run_id: str) -> dict[str, Any]:
    root = _run_root(run_id)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    context: dict[str, Any] = {"run_id": run_id, "root": str(root)}
    if fixture_id == "fixture.noop":
        return context
    if fixture_id == "fixture.notepad_absent":
        context.update({"process_name": "notepad", "baseline_pids": sorted(_process_ids("notepad"))})
    elif fixture_id == "fixture.paint_absent":
        context.update({"process_name": "mspaint", "baseline_pids": sorted(_process_ids("mspaint"))})
    elif fixture_id == "fixture.notepad_running":
        process = subprocess.Popen(["notepad.exe"], close_fds=True)
        context.update({"process_name": "notepad", "fixture_pid": process.pid})
        time.sleep(1)
    elif fixture_id == "fixture.folder_absent":
        context["target"] = str(root / "created-folder")
    elif fixture_id == "fixture.file_absent":
        context.update({"target": str(root / "created.txt"), "content": "MARVIN_FORGE_CONTENT_V1"})
    elif fixture_id == "fixture.rename_source":
        source, target = root / "source.txt", root / "renamed.txt"
        source.write_text("MARVIN_RENAME_V1", encoding="utf-8")
        context.update({"source": str(source), "target": str(target)})
    elif fixture_id == "fixture.copy_source":
        source, target = root / "source.txt", root / "copy.txt"
        source.write_text("MARVIN_COPY_V1", encoding="utf-8")
        context.update({"source": str(source), "target": str(target)})
    elif fixture_id == "fixture.move_source":
        source, destination = root / "source.txt", root / "destination"
        source.write_text("MARVIN_MOVE_V1", encoding="utf-8")
        destination.mkdir()
        context.update(
            {"source": str(source), "destination": str(destination), "target": str(destination / source.name)}
        )
    else:
        raise KeyError(f"Fixture inconnue : {fixture_id}")
    return context


def enrich_prompt(prompt: str, context: dict[str, Any]) -> str:
    public = {key: value for key, value in context.items() if key not in {"baseline_pids", "run_id", "root"}}
    return f"{prompt}\nParamètres exacts de la fixture : {json.dumps(public, ensure_ascii=False)}"


def _powershell_count(command: str) -> int:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return 0
    try:
        return int(completed.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return 0


def oracle(oracle_id: str, context: dict[str, Any]) -> dict[str, Any]:
    passed = False
    evidence: dict[str, Any] = {}
    if oracle_id == "oracle.process_list_nonempty":
        count = len(psutil.pids()); passed = count > 0; evidence = {"process_count": count}
    elif oracle_id in {"oracle.notepad_running", "oracle.paint_running"}:
        current = _process_ids(str(context["process_name"])); baseline = set(context.get("baseline_pids") or [])
        created = sorted(current - baseline); passed = bool(created); evidence = {"new_process_count": len(created)}
        context["created_pids"] = created
    elif oracle_id == "oracle.notepad_absent":
        pid = int(context["fixture_pid"]); passed = not psutil.pid_exists(pid); evidence = {"fixture_pid_running": not passed}
    elif oracle_id == "oracle.services_list_nonempty":
        count = _powershell_count("@(Get-Service).Count"); passed = count > 0; evidence = {"service_count": count}
    elif oracle_id == "oracle.system_info_complete":
        passed = psutil.cpu_count() > 0 and psutil.virtual_memory().total > 0
        evidence = {"cpu_count": psutil.cpu_count(), "ram_bytes": psutil.virtual_memory().total}
    elif oracle_id == "oracle.firewall_observable":
        count = _powershell_count("@(Get-NetFirewallProfile -ErrorAction Stop).Count")
        passed = count >= 3; evidence = {"profile_count": count}
    elif oracle_id == "oracle.network_adapter_present":
        count = len(psutil.net_if_addrs()); passed = count > 0; evidence = {"adapter_count": count}
    elif oracle_id == "oracle.uptime_positive":
        seconds = max(0, int(time.time() - psutil.boot_time())); passed = seconds > 0; evidence = {"uptime_seconds": seconds}
    elif oracle_id == "oracle.software_inventory_nonempty":
        command = "@(Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* -ErrorAction SilentlyContinue).Count"
        count = _powershell_count(command); passed = count > 0; evidence = {"registry_entry_count": count}
    elif oracle_id == "oracle.folder_present":
        target = Path(context["target"]); passed = target.is_dir(); evidence = {"target_exists": passed}
    elif oracle_id == "oracle.file_content_exact":
        target = Path(context["target"]); passed = target.is_file() and target.read_text(encoding="utf-8") == context["content"]
        evidence = {"content_exact": passed}
    elif oracle_id == "oracle.rename_complete":
        passed = Path(context["target"]).is_file() and not Path(context["source"]).exists(); evidence = {"rename_complete": passed}
    elif oracle_id == "oracle.copy_hash_equal":
        source, target = Path(context["source"]), Path(context["target"])
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        passed = source.is_file() and target.is_file() and digest(source) == digest(target); evidence = {"hash_equal": passed}
    elif oracle_id == "oracle.move_complete":
        passed = Path(context["target"]).is_file() and not Path(context["source"]).exists(); evidence = {"move_complete": passed}
    else:
        raise KeyError(f"Oracle inconnu : {oracle_id}")
    return {"passed": passed, "evidence": evidence}


def teardown(context: dict[str, Any]) -> None:
    allowed_pids = set(context.get("created_pids") or [])
    fixture_pid = context.get("fixture_pid")
    if fixture_pid:
        allowed_pids.add(int(fixture_pid))
    for pid in allowed_pids:
        try:
            process = psutil.Process(pid)
            process.terminate()
            process.wait(timeout=3)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired, psutil.AccessDenied):
            continue
    root = Path(str(context.get("root") or "")).resolve()
    if root != FIXTURE_ROOT and FIXTURE_ROOT in root.parents:
        shutil.rmtree(root, ignore_errors=True)


FIXTURE_IDS = {
    "fixture.noop", "fixture.notepad_absent", "fixture.paint_absent", "fixture.notepad_running",
    "fixture.folder_absent", "fixture.file_absent", "fixture.rename_source", "fixture.copy_source", "fixture.move_source",
}
ORACLE_IDS = {
    "oracle.process_list_nonempty", "oracle.notepad_running", "oracle.paint_running", "oracle.notepad_absent",
    "oracle.services_list_nonempty", "oracle.system_info_complete", "oracle.firewall_observable",
    "oracle.network_adapter_present", "oracle.uptime_positive", "oracle.software_inventory_nonempty",
    "oracle.folder_present", "oracle.file_content_exact", "oracle.rename_complete", "oracle.copy_hash_equal", "oracle.move_complete",
}
