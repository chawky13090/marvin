from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import bulk_rename_rollback_store as store

def main() -> int:
    parser = argparse.ArgumentParser(description="Maintenance bornée des rollbacks bulk_rename.")
    commands = parser.add_subparsers(dest="command", required=True)
    migrate = commands.add_parser("migrate"); migrate.add_argument("--root", type=Path, required=True)
    rollback = commands.add_parser("rollback-migration"); rollback.add_argument("--manifest", required=True)
    acknowledge = commands.add_parser("acknowledge"); acknowledge.add_argument("--manifest", required=True); acknowledge.add_argument("--extend-days", type=int, default=0)
    commands.add_parser("status")
    args = parser.parse_args()
    if args.command == "migrate":
        result = {"migrated": store.migrate_legacy_for_root(args.root.resolve()), "global_scan": False}
    elif args.command == "rollback-migration":
        result = {"restored_legacy_manifest": store.rollback_legacy_migration(args.manifest)}
    elif args.command == "acknowledge":
        import time
        retain_until = time.time() + args.extend_days * 86400 if args.extend_days else None
        store.acknowledge(args.manifest, retain_until=retain_until)
        result = {"acknowledged": True, "retention_extended_days": args.extend_days}
    else:
        result = store.status()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__": raise SystemExit(main())
