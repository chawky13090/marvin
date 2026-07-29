"""Restaure hors ligne un bundle global local Marvin avec compensation."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import full_backup
import full_backup_recovery


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.4)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Appliquer un bundle Marvin local, backend et frontend arrêtés."
    )
    parser.add_argument("filename", help="Nom marvin_full_*.mrvfull présent dans data/backups")
    parser.add_argument(
        "--confirm-offline-restore",
        action="store_true",
        help="Confirme le remplacement de l'état autoritatif après création d'un rollback.",
    )
    arguments = parser.parse_args()
    if not arguments.confirm_offline_restore:
        parser.error("--confirm-offline-restore est obligatoire.")
    active = [port for port in (8005, 3000) if _port_open(port)]
    if active:
        print(json.dumps({
            "success": False,
            "error_code": "marvin_still_running",
            "ports": active,
        }))
        return 2
    try:
        source = full_backup.resolve(arguments.filename)
        result = full_backup_recovery.apply_offline(source)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({
            "success": False,
            "error_code": type(exc).__name__,
        }))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
