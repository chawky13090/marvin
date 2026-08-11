"""Inventory, integrity evidence and safe plans for Marvin's Hyper-V lab."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Final

from config import DATA_DIR
import storage_layout


VERIFICATION_PATH: Final[Path] = Path(DATA_DIR) / "vm_lab_iso_verification.json"
PROFILES: Final[dict[str, dict[str, Any]]] = {
    "windows11": {
        "vm_name": "Marvin-Windows11-TestForge",
        "category": "windows",
        "iso_name": "Win11_25H2_French_x64_v2.iso",
        "hash_algorithm": "sha256",
        "expected_hash": "A02693BEB8EB166AFDFDB7DB49176A2B547F81E61030A695FE172277DB6A1977",
        "memory_bytes": 4 * 1024**3,
        "memory_maximum_bytes": 6 * 1024**3,
        "processors": 4,
        "disk_bytes": 80 * 1024**3,
        "minimum_free_bytes": 80 * 1024**3,
        "secure_boot_template": "MicrosoftWindows",
        "vtpm": True,
    },
    "debian13": {
        "vm_name": "Marvin-Debian13-TestForge",
        "category": "linux",
        "iso_name": "debian-13.6.0-amd64-netinst.iso",
        "hash_algorithm": "sha512",
        "expected_hash": (
            "CE0EEEE7B51FDCDBED1E5116668C1FEE27E528767BDF488E5F115A67B225E5DF"
            "D0AFCA1D456AAA9408CEB6B8527521FF7B6B5D62FDBE6F8C5FAAF8DF56A96292"
        ),
        "memory_bytes": 4 * 1024**3,
        "memory_maximum_bytes": 4 * 1024**3,
        "processors": 4,
        "disk_bytes": 40 * 1024**3,
        "minimum_free_bytes": 25 * 1024**3,
        "secure_boot_template": "MicrosoftUEFICertificateAuthority",
        "vtpm": False,
    },
}


class VMLabError(RuntimeError):
    pass


def _verification_records() -> dict[str, Any]:
    try:
        value = json.loads(VERIFICATION_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_records(value: dict[str, Any]) -> None:
    VERIFICATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = VERIFICATION_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, VERIFICATION_PATH)


def _iso_path(profile: dict[str, Any]) -> Path:
    layout = storage_layout.status()
    key = "iso_windows" if profile["category"] == "windows" else "iso_linux"
    return Path(layout["directories"][key]) / profile["iso_name"]


def _hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def verify_isos(*, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise VMLabError("La vérification complète des ISO doit être confirmée.")
    records = _verification_records()
    results = []
    for profile_id, profile in PROFILES.items():
        path = _iso_path(profile)
        if not path.is_file():
            results.append({"profile": profile_id, "path": str(path), "present": False, "verified": False})
            continue
        stat = path.stat()
        observed = _hash(path, profile["hash_algorithm"])
        verified = observed == profile["expected_hash"]
        record = {
            "profile": profile_id,
            "path": str(path.resolve()),
            "size_bytes": stat.st_size,
            "modified_ns": stat.st_mtime_ns,
            "algorithm": profile["hash_algorithm"],
            "hash": observed,
            "expected_hash": profile["expected_hash"],
            "verified": verified,
            "verified_at": time.time(),
        }
        records[profile_id] = record
        results.append({**record, "present": True})
    _write_records(records)
    return {"results": results, "all_verified": bool(results) and all(item["verified"] for item in results)}


def _record_is_current(profile_id: str, path: Path) -> bool:
    record = _verification_records().get(profile_id) or {}
    try:
        stat = path.stat()
    except OSError:
        return False
    return bool(
        record.get("verified")
        and Path(str(record.get("path"))).resolve() == path.resolve()
        and record.get("size_bytes") == stat.st_size
        and record.get("modified_ns") == stat.st_mtime_ns
        and record.get("expected_hash") == PROFILES[profile_id]["expected_hash"]
    )


def _hyperv_status() -> dict[str, Any]:
    script = r"""
$ErrorActionPreference = 'Stop'
Import-Module Hyper-V
$switches = @(Get-VMSwitch | ForEach-Object { [ordered]@{ name=$_.Name; type=[string]$_.SwitchType } })
$labNames = @('Marvin-Windows11-TestForge','Marvin-Debian13-TestForge')
$vms = @()
foreach ($name in $labNames) {
  try {
    $vm = Get-VM -Name $name -ErrorAction Stop
    $vms += [ordered]@{ name=$vm.Name; state=[string]$vm.State; generation=$vm.Generation; path=$vm.Path }
  } catch {
    if ($_.FullyQualifiedErrorId -notlike 'ObjectNotFound*' -and $_.FullyQualifiedErrorId -notlike 'InvalidParameter*') { throw }
  }
}
[ordered]@{ access=$true; switches=$switches; vms=$vms } | ConvertTo-Json -Depth 5 -Compress
"""
    executable = os.environ.get("SystemRoot", r"C:\Windows") + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
    try:
        result = subprocess.run(
            [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"access": False, "switches": [], "vms": [], "error": str(exc)}
    if result.returncode:
        return {"access": False, "switches": [], "vms": [], "error": (result.stderr or result.stdout).strip()[:1500]}
    try:
        return json.loads(result.stdout.strip())
    except (TypeError, json.JSONDecodeError):
        return {"access": False, "switches": [], "vms": [], "error": "Réponse Hyper-V invalide."}


def status() -> dict[str, Any]:
    layout = storage_layout.status()
    free_bytes = int(layout["machine"].get("free_bytes") or 0)
    profiles = []
    for profile_id, profile in PROFILES.items():
        path = _iso_path(profile)
        profiles.append({
            "id": profile_id,
            **{key: value for key, value in profile.items() if key not in {"expected_hash"}},
            "iso_path": str(path),
            "iso_present": path.is_file(),
            "iso_verified": _record_is_current(profile_id, path),
            "capacity_ready": free_bytes >= profile["minimum_free_bytes"],
            "vm_path": str(Path(layout["directories"]["vm_windows" if profile["category"] == "windows" else "vm_linux"]) / profile["vm_name"]),
        })
    combined_minimum = sum(int(profile["minimum_free_bytes"]) for profile in PROFILES.values())
    hyperv = _hyperv_status()
    switch_names = {str(item.get("name")) for item in hyperv.get("switches", [])}
    return {
        "profiles": profiles,
        "machine_root": layout["machine_root"],
        "free_bytes": free_bytes,
        "combined_minimum_free_bytes": combined_minimum,
        "combined_capacity_ready": free_bytes >= combined_minimum,
        "hyperv": hyperv,
        "installation_switch": "Default Switch" if "Default Switch" in switch_names else None,
        "host_network_policy": "host_unchanged_guest_connected_only_during_installation",
        "provisioning_ready": bool(
            hyperv.get("access") and "Default Switch" in switch_names
            and all(item["iso_verified"] and item["capacity_ready"] for item in profiles)
        ),
    }
