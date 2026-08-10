"""Construit atomiquement l'inventaire de preuve des outils Marvin."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from tool_evidence_inventory import ROOT, build_inventory


def _write_atomic(destination: Path, payload: dict) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database", type=Path, default=ROOT / "data" / "secretary.db"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "benchmarks" / "tool-evidence" / "v1" / "inventory.json",
    )
    args = parser.parse_args()
    payload = build_inventory(args.database)
    _write_atomic(args.output.resolve(), payload)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
