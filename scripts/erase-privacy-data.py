"""Effacement hors ligne compensé d'une sélection exacte de preuves Marvin."""

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


def _backend_is_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", 8005)) == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Effacer et rechaîner des preuves sélectionnées.")
    parser.add_argument("stream_id")
    parser.add_argument("selector")
    parser.add_argument("rollback_destination", type=Path)
    parser.add_argument("--confirmed", action="store_true")
    arguments = parser.parse_args()
    if not arguments.confirmed:
        print(json.dumps({"success": False, "error_code": "ConfirmationRequired"}))
        return 2
    if _backend_is_running():
        print(json.dumps({"success": False, "error_code": "BackendStillRunning"}))
        return 2
    selector_value = getpass.getpass("Valeur exacte à effacer : ")
    passphrase = getpass.getpass("Phrase secrète du rollback : ")
    confirmation = getpass.getpass("Confirmer la phrase secrète : ")
    if passphrase != confirmation:
        print(json.dumps({"success": False, "error_code": "PassphraseMismatch"}))
        return 2
    try:
        result = privacy_rights.erase_exact(
            arguments.stream_id,
            arguments.selector,
            selector_value,
            arguments.rollback_destination,
            passphrase=passphrase,
            confirmed=True,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error_code": type(exc).__name__}))
        return 1
    finally:
        selector_value = ""
        passphrase = ""
        confirmation = ""


if __name__ == "__main__":
    raise SystemExit(main())
