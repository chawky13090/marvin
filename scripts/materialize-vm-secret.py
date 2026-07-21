"""Materialize a DPAPI secret to a caller-protected temporary path."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import dpapi_secret_store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    value = dpapi_secret_store.get_secret(args.key)
    if not value:
        raise SystemExit("Secret DPAPI absent.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(value, encoding="ascii", newline="\n")
    os.replace(temporary, args.output)
    value = ""
    print("Secret matérialisé dans le fichier temporaire protégé demandé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

