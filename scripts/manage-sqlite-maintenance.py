"""CLI hors ligne de maintenance et rollback SQLite Marvin."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlite_maintenance import service


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("run", "rollback"))
    parser.add_argument("--backup")
    args = parser.parse_args()
    if args.action == "rollback":
        if not args.backup:
            parser.error("--backup est requis pour rollback")
        result = service.rollback(args.backup)
    else:
        result = service.run()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
