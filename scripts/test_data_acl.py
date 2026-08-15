"""Contrat réel du durcissement et rollback ACL Windows."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "manage-data-acl.ps1"


def _windows_powershell_env() -> dict[str, str]:
    # Un parent PowerShell 7 peut imposer son PSModulePath à Windows
    # PowerShell 5.1 et masquer ses modules système. Sans override, le shell
    # enfant reconstruit ses chemins natifs de manière portable.
    return {key: value for key, value in os.environ.items() if key.casefold() != "psmodulepath"}


def _run(*args: str) -> dict:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            *args,
        ],
        cwd=ROOT,
        env=_windows_powershell_env(),
        capture_output=True,
        check=False,
        timeout=60,
    )
    stdout = completed.stdout.decode("utf-8", errors="replace").strip().splitlines()
    if completed.returncode != 0 or not stdout:
        stderr = completed.stderr.decode("utf-8", errors="replace")[-500:]
        output = completed.stdout.decode("utf-8", errors="replace")[-500:]
        raise AssertionError(
            f"ACL script failed ({completed.returncode}): stdout={output} stderr={stderr}"
        )
    return json.loads(stdout[-1])


def _run_failure(*args: str) -> str:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            *args,
        ],
        cwd=ROOT,
        env=_windows_powershell_env(),
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert completed.returncode != 0
    return (completed.stdout + completed.stderr).decode("utf-8", errors="replace")


def main() -> int:
    if os.name != "nt":
        print("Data ACL SKIP - Windows requis.")
        return 0
    with tempfile.TemporaryDirectory(prefix="marvin-data-acl-") as directory:
        root = Path(directory)
        data = root / "data"
        runtime = root / "runtime" / "security"
        (data / "backups").mkdir(parents=True)
        (data / "maintenance").mkdir()
        (data / "secretary.db").write_bytes(b"db")
        (data / "windows_secrets.dpapi.json").write_text("{}", encoding="utf-8")

        before = _run("-Action", "Audit", "-DataRoot", str(data), "-RuntimeRoot", str(runtime))
        assert before["success"] is True
        assert before["status"]["inheritance_protected"] is False

        applied = _run(
            "-Action", "Apply", "-DataRoot", str(data), "-RuntimeRoot", str(runtime), "-NoConfirm"
        )
        assert applied["success"] is True
        assert applied["status"]["compliant"] is True
        backup = Path(applied["backup_path"])
        assert backup.is_file() and len(applied["backup_sha256"]) == 64
        assert backup.with_name(backup.name + ".json").is_file()

        original_backup = backup.read_bytes()
        backup.write_bytes(original_backup + b"tampered")
        failure = _run_failure(
            "-Action", "Restore", "-DataRoot", str(data), "-RuntimeRoot", str(runtime),
            "-BackupPath", str(backup), "-NoConfirm"
        )
        assert "empreinte" in failure.lower()
        backup.write_bytes(original_backup)

        restored = _run(
            "-Action", "Restore", "-DataRoot", str(data), "-RuntimeRoot", str(runtime),
            "-BackupPath", str(backup), "-NoConfirm"
        )
        assert restored["success"] is True
        assert restored["status"]["inheritance_protected"] is False

    print("Data ACL OK - audit, sauvegarde, durcissement récursif et rollback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
