"""Crée un export portable Marvin sans exposer la phrase secrète dans la CLI."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import portable_backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Créer un export Marvin portable chiffré.")
    parser.add_argument("destination", type=Path, help="Nouveau fichier .mrvportable")
    arguments = parser.parse_args()
    first = getpass.getpass("Phrase secrète de l'export portable : ")
    second = getpass.getpass("Confirmer la phrase secrète : ")
    if first != second:
        print(json.dumps({"success": False, "error_code": "PassphraseMismatch"}))
        return 2
    try:
        result = portable_backup.create(arguments.destination, passphrase=first)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error_code": type(exc).__name__}))
        return 1
    finally:
        first = ""
        second = ""


if __name__ == "__main__":
    raise SystemExit(main())
