from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import python_runtime


def _write_config(root: Path, home: str, executable: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyvenv.cfg").write_text(
        f"home = {home}\nexecutable = {executable}\n",
        encoding="utf-8",
    )


with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
    root = Path(temporary)
    stable_python = root / "Python313" / "python.exe"
    stable_python.parent.mkdir(parents=True)
    stable_python.write_bytes(b"runtime")
    stable_venv = root / "stable-venv"
    _write_config(stable_venv, str(stable_python.parent), str(stable_python))
    stable = python_runtime.inspect_runtime(
        executable=stable_venv / "Scripts" / "python.exe",
        base_executable=stable_python,
        venv_root=stable_venv,
        version_info=(3, 13),
    )
    assert stable["portable"] is True
    assert stable["reasons"] == []

    ephemeral_python = root / ".cache" / "codex-runtimes" / "python.exe"
    ephemeral_python.parent.mkdir(parents=True)
    ephemeral_python.write_bytes(b"runtime")
    ephemeral_venv = root / "ephemeral-venv"
    _write_config(ephemeral_venv, str(ephemeral_python.parent), str(ephemeral_python))
    ephemeral = python_runtime.inspect_runtime(
        executable=ephemeral_venv / "Scripts" / "python.exe",
        base_executable=ephemeral_python,
        venv_root=ephemeral_venv,
        version_info=(3, 12),
    )
    assert ephemeral["portable"] is False
    assert "ephemeral_runtime" in ephemeral["reasons"]

    unsupported = python_runtime.inspect_runtime(
        executable=stable_venv / "Scripts" / "python.exe",
        base_executable=stable_python,
        venv_root=stable_venv,
        version_info=(3, 14),
    )
    assert unsupported["portable"] is False
    assert "unsupported_version" in unsupported["reasons"]

print("Python runtime provenance tests passed.")
