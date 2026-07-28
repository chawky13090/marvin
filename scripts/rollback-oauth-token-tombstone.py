"""Rollback explicite de la migration OAuth v2.424 vers le schéma en clair."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config import DB_PATH
from oauth_legacy_migration import rollback_legacy_tokens


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restaure temporairement l'ancien stockage OAuth SQLite en clair."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--accept-plaintext", action="store_true")
    args = parser.parse_args()
    if not args.apply or not args.accept_plaintext:
        parser.error("--apply et --accept-plaintext sont obligatoires.")
    connection = sqlite3.connect(Path(DB_PATH))
    try:
        restored = rollback_legacy_tokens(connection, confirmed=True)
    finally:
        connection.close()
    print(f"Rollback OAuth terminé : {restored} fournisseur(s) restauré(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
