"""Rollback explicite des secrets e-mail DPAPI vers SQLite en clair."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import email_accounts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--accept-plaintext", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        accounts = email_accounts._list_persisted()
        print(json.dumps({
            "accounts": len(accounts),
            "vault_references": sum(
                bool(account.get("_secret_ref")) for account in accounts
            ),
        }, sort_keys=True))
        return 0
    if not args.accept_plaintext:
        raise SystemExit("--accept-plaintext est obligatoire.")
    count = email_accounts.rollback_secrets_to_sqlite(confirmed=True)
    print(json.dumps({"success": True, "accounts": count}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
