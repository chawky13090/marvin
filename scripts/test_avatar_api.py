"""Régressions du contrôle local de l'avatar sans lancer Electron."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api import avatar


def main() -> int:
    assert avatar._is_loopback("127.0.0.1") is True
    assert avatar._is_loopback("::1") is True
    assert avatar._is_loopback("192.168.1.20") is False
    fake = type("Process", (), {"info": {
        "pid": 42,
        "exe": str(avatar.ELECTRON),
        "cmdline": [str(avatar.ELECTRON), str(avatar.ENTRYPOINT)],
    }})()
    with patch.object(avatar.psutil, "process_iter", return_value=[fake]):
        assert avatar._running() == [42]
    source = (ROOT / "backend" / "api" / "avatar.py").read_text(encoding="utf-8")
    assert "DETACHED_PROCESS" in source
    assert "subprocess.DEVNULL" in source
    print("Avatar API OK - activation locale, détection et processus borné.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
