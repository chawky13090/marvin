"""Extrait les demandes réelles dans deux enveloppes DPAPI séparées."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dpapi_secret_store import protect_bytes, unprotect_bytes  # noqa: E402
from real_usage_corpus import publish_private_extraction  # noqa: E402


def _protect(value: bytes, purpose: str) -> bytes:
    return protect_bytes(value, purpose=purpose)


def _unprotect(value: bytes, purpose: str) -> bytes:
    return unprotect_bytes(value, purpose=purpose)


def main() -> int:
    manifest = publish_private_extraction(
        database_path=ROOT / "data" / "secretary.db",
        private_directory=ROOT / "data" / "forge" / "real-usage-v1",
        public_manifest_path=(
            ROOT / "benchmarks" / "tool-evidence" / "v1" / "real-usage-extraction-manifest.json"
        ),
        protect=_protect,
        unprotect=_unprotect,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
