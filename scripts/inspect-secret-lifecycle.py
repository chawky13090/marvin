"""Diagnostic non sensible du coffre DPAPI pour installation et support."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import dpapi_secret_store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        result = dpapi_secret_store.lifecycle_status(verify_decryption=args.verify)
        result["status"] = "reauthentication_required" if result["reauthentication_required"] else "ready"
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2 if result["reauthentication_required"] else 0
    except Exception as exc:
        print(json.dumps({
            "status": "invalid",
            "error_type": type(exc).__name__,
            "reauthentication_required": True,
            "portable": False,
        }, sort_keys=True))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
