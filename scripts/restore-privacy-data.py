"""Restaure hors ligne un rollback chiffré d'effacement de preuves."""

from __future__ import annotations

import argparse
import getpass
import json
import socket
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import privacy_rights


def main() -> int:
    parser = argparse.ArgumentParser(description="Restaurer un rollback personnel Marvin.")
    parser.add_argument("stream_id")
    parser.add_argument("rollback_source", type=Path)
    parser.add_argument("--confirmed", action="store_true")
    arguments = parser.parse_args()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        if probe.connect_ex(("127.0.0.1", 8005)) == 0:
            print(json.dumps({"success": False, "error_code": "BackendStillRunning"}))
            return 2
    if not arguments.confirmed:
        print(json.dumps({"success": False, "error_code": "ConfirmationRequired"}))
        return 2
    passphrase = getpass.getpass("Phrase secrète du rollback : ")
    try:
        result = privacy_rights.restore_rollback(
            arguments.stream_id,
            arguments.rollback_source,
            passphrase=passphrase,
            confirmed=True,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error_code": type(exc).__name__}))
        return 1
    finally:
        passphrase = ""


if __name__ == "__main__":
    raise SystemExit(main())
