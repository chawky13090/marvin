"""Migration, statut et rollback explicite du compte de service Google."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import google_service_account_vault as vault


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "migrate", "rollback"))
    parser.add_argument("--acknowledge-plaintext-risk", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "migrate":
            vault.migrate_legacy()
        elif args.action == "rollback":
            vault.restore_legacy_for_rollback(
                acknowledge_plaintext_risk=args.acknowledge_plaintext_risk
            )
        status = vault.security_status()
    except vault.GoogleServiceAccountVaultError as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"success": True, **status}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
