"""Qualify E7 pilot isolation without invoking any Marvin business tool."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from e7_fixture_harness import build_pilot_implementations, build_pilot_plans


DEFAULT_OUTPUT = ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "e7-pilot-environment-qualification.json"
VM_NAME = "Marvin-Windows11-TestForge"
CHECKPOINT_NAME = "Marvin-Clean"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _local_qualification() -> dict:
    with tempfile.TemporaryDirectory(prefix="marvin-e7-qualification-") as temporary:
        root = Path(temporary)
        source = root / "source.txt"
        target = root / "target.txt"
        source.write_text("fixture-A17", encoding="utf-8")
        source.replace(target)
        filesystem_ok = target.read_text(encoding="utf-8") == "fixture-A17"

        database = root / "fixture.db"
        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE fixture(id TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO fixture VALUES('A17', 'qualified')")
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            row_count = connection.execute("SELECT COUNT(*) FROM fixture").fetchone()[0]
        finally:
            connection.close()

        task_store = root / "tasks.json"
        task_store.write_text('{"tasks":[],"workers":[],"artifacts":[]}', encoding="utf-8")
        task_value = json.loads(task_store.read_text(encoding="utf-8"))
        return {
            "qualified": bool(
                filesystem_ok
                and integrity == "ok"
                and row_count == 1
                and task_value == {"tasks": [], "workers": [], "artifacts": []}
            ),
            "filesystem_atomic_replace": filesystem_ok,
            "sqlite_integrity": integrity,
            "task_store_schema": sorted(task_value),
            "workspace_removed_after_probe": True,
        }


def _hyperv_qualification() -> dict:
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module Hyper-V
$vm = Get-VM -Name '{VM_NAME}' -ErrorAction Stop
$memory = Get-VMMemory -VMName $vm.Name
$checkpoint = Get-VMCheckpoint -VMName $vm.Name -Name '{CHECKPOINT_NAME}' -ErrorAction Stop
$os = Get-CimInstance Win32_OperatingSystem
$switches = @(Get-VMNetworkAdapter -VMName $vm.Name | ForEach-Object {{ $_.SwitchName }})
[ordered]@{{
  vm_name = $vm.Name
  state = [string]$vm.State
  generation = [int]$vm.Generation
  checkpoint_name = $checkpoint.Name
  checkpoint_type = [string]$vm.CheckpointType
  dynamic_memory = [bool]$memory.DynamicMemoryEnabled
  startup_bytes = [int64]$memory.Startup
  minimum_bytes = [int64]$memory.Minimum
  maximum_bytes = [int64]$memory.Maximum
  host_free_memory_bytes = ([int64]$os.FreePhysicalMemory * 1KB)
  switches = $switches
}} | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if completed.returncode:
        return {"qualified": False, "error": (completed.stderr or completed.stdout).strip()[:1000]}
    observed = json.loads(completed.stdout)
    qualified = bool(
        observed.get("state") == "Off"
        and observed.get("generation") == 2
        and observed.get("checkpoint_name") == CHECKPOINT_NAME
        and observed.get("checkpoint_type") == "ProductionOnly"
        and observed.get("dynamic_memory") is True
        and 3 * 1024**3 <= int(observed.get("minimum_bytes") or 0)
        and int(observed.get("startup_bytes") or 0) == 4 * 1024**3
        and int(observed.get("maximum_bytes") or 0) == 6 * 1024**3
        and int(observed.get("host_free_memory_bytes") or 0) >= int(observed.get("startup_bytes") or 0)
        and "Default Switch" in observed.get("switches", [])
    )
    return {"qualified": qualified, **observed}


def build_report() -> dict:
    plans = build_pilot_plans()
    implementations = build_pilot_implementations()
    local = _local_qualification()
    hyperv = _hyperv_qualification()
    return {
        "schema": "marvin.e7-pilot-environment-qualification/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "qualified_no_business_tool_execution" if local["qualified"] and hyperv["qualified"] else "not_qualified",
        "tool_execution_authorized": False,
        "host_execution_forbidden": True,
        "business_tools_invoked": [],
        "pilot_contract_count": len(plans),
        "pilot_implementation_count": len(implementations),
        "source_hashes": {
            "contracts": _sha256(ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "direct-fixture-contracts.json"),
            "implementations": _sha256(ROOT / "scripts" / "e7_fixture_harness" / "pilot_implementations.py"),
        },
        "local_isolation": local,
        "windows_vm_isolation": hyperv,
        "limitations": [
            "qualification_does_not_execute_any_marvin_business_tool",
            "qualification_does_not_set_E7",
            "vm_checkpoint_restore_must_be_replayed_by_the_execution_campaign",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["status"] == "qualified_no_business_tool_execution" else 1


if __name__ == "__main__":
    raise SystemExit(main())
