"""CLI prudente pour chiffrer ou restaurer les sauvegardes Marvin."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from backup import BACKUP_DIR
from backup_migration import migrate_directory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--direction", choices=("up", "down"), required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", type=Path, default=BACKUP_DIR)
    args = parser.parse_args()
    print(json.dumps(migrate_directory(args.backup_dir, direction=args.direction, apply=args.apply), ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
