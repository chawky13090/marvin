"""Generate VM answer files without printing credentials."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import vm_unattended


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=("debian13", "windows11"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--windows-image-index", type=int, default=1)
    args = parser.parse_args()
    if args.profile == "debian13":
        result = vm_unattended.prepare_debian(args.output)
    else:
        result = vm_unattended.prepare_windows(args.output, image_index=args.windows_image_index)
    safe = {key: value for key, value in result.items() if key not in {"public_key"}}
    print(json.dumps(safe, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

