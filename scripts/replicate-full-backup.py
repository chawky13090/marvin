"""Copie explicitement un bundle global chiffré vers un autre stockage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import backup_replication
import full_backup


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Répliquer un bundle Marvin chiffré vers un stockage choisi."
    )
    parser.add_argument("filename", help="Nom marvin_full_*.mrvfull dans data/backups")
    parser.add_argument("destination", type=Path, help="Racine existante du stockage cible")
    parser.add_argument(
        "--confirm-external-copy",
        action="store_true",
        help="Confirme la copie potentiellement externe du bundle chiffré.",
    )
    arguments = parser.parse_args()
    if not arguments.confirm_external_copy:
        parser.error("--confirm-external-copy est obligatoire.")
    try:
        result = backup_replication.replicate(
            full_backup.resolve(arguments.filename),
            arguments.destination,
        )
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
