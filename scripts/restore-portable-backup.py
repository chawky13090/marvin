"""Vérifie et restaure un export portable vers un dossier isolé."""

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
    parser = argparse.ArgumentParser(
        description="Restaurer un export Marvin portable vers un dossier vide isolé."
    )
    parser.add_argument("source", type=Path, help="Fichier .mrvportable")
    parser.add_argument("destination", type=Path, help="Dossier isolé vide ou absent")
    arguments = parser.parse_args()
    passphrase = getpass.getpass("Phrase secrète de l'export portable : ")
    try:
        result = portable_backup.restore_to(
            arguments.source,
            arguments.destination,
            passphrase=passphrase,
        )
        result["manifest"] = None
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error_code": type(exc).__name__}))
        return 1
    finally:
        passphrase = ""


if __name__ == "__main__":
    raise SystemExit(main())
