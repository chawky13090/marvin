"""Deterministic checks for Marvin's classified portable storage."""
from __future__ import annotations

import tempfile
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import storage_layout


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="marvin-storage-test-") as temporary:
        base = Path(temporary)
        machine = base / "machine"
        exports = base / "exports"
        config = base / "layout.json"
        with (
            patch.object(storage_layout, "CONFIG_PATH", config),
            patch.object(storage_layout, "_default_roots", return_value=(machine, exports)),
            patch.object(storage_layout, "_drive_type", return_value="fixed"),
            patch.object(storage_layout, "_cloud_roots", return_value=[]),
        ):
            initial = storage_layout.status()
            assert not initial["machine_exists"]
            try:
                storage_layout.ensure(confirmed=False)
                raise AssertionError("Une création non confirmée a été acceptée.")
            except storage_layout.StorageLayoutError:
                pass
            created = storage_layout.ensure(confirmed=True)
            assert created["machine_exists"] and created["export_exists"]
            for path in created["directories"].values():
                assert Path(path).is_dir()
            iso = Path(created["directories"]["iso_linux"]) / "debian-netinst.iso"
            iso.write_bytes(b"test-iso")
            inventory = storage_layout.status()["iso_inventory"]
            assert inventory[0]["category"] == "linux"
            assert inventory[0]["name"] == iso.name
            configured = storage_layout.configure(
                machine_root=str(base / "machine-2"), export_root=str(base / "exports-2"),
                confirmed=True,
            )
            assert configured["configured"]
        with (
            patch.object(storage_layout, "_drive_type", return_value="network"),
            patch.object(storage_layout, "_cloud_roots", return_value=[]),
        ):
            assert not storage_layout.validate_machine_root(base / "unsafe")["valid"]
    print("Storage Layout OK - racines séparées, inventaire ISO et refus des disques réseau.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
