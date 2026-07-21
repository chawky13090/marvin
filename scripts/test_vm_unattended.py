"""Regression tests for unattended VM material and DPAPI handling."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import vm_unattended


def main() -> int:
    secrets: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="marvin-unattended-") as temporary, patch.object(
        vm_unattended.dpapi_secret_store, "set_secret", side_effect=secrets.__setitem__
    ):
        root = Path(temporary)
        debian = vm_unattended.prepare_debian(root / "debian")
        preseed = Path(debian["preseed_path"]).read_text(encoding="utf-8")
        assert "ssh-ed25519" in preseed
        assert "PasswordAuthentication no" in preseed
        assert secrets[vm_unattended.DEBIAN_KEY_SECRET].startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
        assert secrets[vm_unattended.DEBIAN_KEY_SECRET] not in preseed
        windows = vm_unattended.prepare_windows(root / "windows", image_index=6)
        answer = Path(windows["answer_path"]).read_text(encoding="utf-8")
        password = secrets[vm_unattended.WINDOWS_PASSWORD_SECRET]
        assert len(password) == 32
        assert password in answer
        assert "<Value>6</Value>" in answer
        assert "VK7JG-NPHTM-C97JM-9MPGT-3V66T" in answer
        assert "<Group>Administrators</Group>" in answer
        assert password not in Path(windows["metadata_path"]).read_text(encoding="utf-8")
    print("VM unattended OK - SSH sans mot de passe et secret Windows protégé par DPAPI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
