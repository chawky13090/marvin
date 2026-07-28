"""Rollback explicite des secrets SSH DPAPI vers SQLite en clair."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from repositories.ssh_connections import repository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--accept-plaintext", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({
            "connections": len(repository.list_connections()),
        }, sort_keys=True))
        return 0
    if not args.accept_plaintext:
        raise SystemExit("--accept-plaintext est obligatoire.")
    count = repository.rollback_secrets_to_sqlite(confirmed=True)
    print(json.dumps({"success": True, "connections": count}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
