"""Deterministic tests for VM Lab inventory and ISO integrity evidence."""
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import vm_lab


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="marvin-vm-lab-") as temporary:
        base = Path(temporary)
        windows_iso = base / "windows.iso"
        linux_iso = base / "linux.iso"
        windows_iso.write_bytes(b"windows-test-media")
        linux_iso.write_bytes(b"linux-test-media")
        profiles = {
            "windows11": {**vm_lab.PROFILES["windows11"], "iso_name": windows_iso.name,
                          "expected_hash": hashlib.sha256(windows_iso.read_bytes()).hexdigest().upper()},
            "debian13": {**vm_lab.PROFILES["debian13"], "iso_name": linux_iso.name,
                         "expected_hash": hashlib.sha512(linux_iso.read_bytes()).hexdigest().upper()},
        }
        layout = {
            "machine_root": str(base), "machine": {"free_bytes": 500 * 1024**3},
            "directories": {"iso_windows": str(base), "iso_linux": str(base),
                            "vm_windows": str(base / "vm-win"), "vm_linux": str(base / "vm-linux")},
        }
        with (
            patch.object(vm_lab, "PROFILES", profiles),
            patch.object(vm_lab, "VERIFICATION_PATH", base / "records.json"),
            patch.object(vm_lab.storage_layout, "status", return_value=layout),
            patch.object(vm_lab, "_hyperv_status", return_value={
                "access": True, "switches": [{"name": "Default Switch", "type": "Internal"}], "vms": []}),
        ):
            try:
                vm_lab.verify_isos(confirmed=False)
                raise AssertionError("Une vérification non confirmée a été acceptée.")
            except vm_lab.VMLabError:
                pass
            verified = vm_lab.verify_isos(confirmed=True)
            assert verified["all_verified"]
            state = vm_lab.status()
            assert state["provisioning_ready"]
            assert all(item["iso_verified"] for item in state["profiles"])
            windows_iso.write_bytes(b"tampered")
            state = vm_lab.status()
            assert not state["provisioning_ready"]
            assert not state["profiles"][0]["iso_verified"]
    print("VM Lab OK - empreintes, invalidation, capacité et prérequis Hyper-V.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
