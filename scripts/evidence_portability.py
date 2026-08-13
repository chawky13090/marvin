"""Identité portable des preuves textuelles sans affaiblir les gels historiques."""

from __future__ import annotations

import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ERRATUM = ROOT / "benchmarks" / "evidence-portability" / "v1" / "line-ending-erratum.json"
UTF8_BOM = b"\xef\xbb\xbf"
TEXT_SUFFIXES = {
    ".cfg", ".css", ".html", ".ini", ".js", ".json", ".jsx", ".md", ".mjs",
    ".ps1", ".py", ".sh", ".toml", ".txt", ".xml", ".yaml", ".yml",
}


def canonical_bytes_from_bytes(payload: bytes, *, suffix: str) -> bytes:
    """Normalise seulement les fins de ligne d'un texte UTF-8 reconnu."""
    if suffix.casefold() not in TEXT_SUFFIXES:
        return payload
    if payload.startswith(UTF8_BOM):
        raise ValueError("utf8_bom_forbidden_for_canonical_evidence")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("canonical_evidence_must_be_utf8") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def canonical_bytes(path: Path) -> bytes:
    return canonical_bytes_from_bytes(path.read_bytes(), suffix=path.suffix)


def canonical_sha256(path: Path) -> str:
    return hashlib.sha256(canonical_bytes(path)).hexdigest()


def canonical_size(path: Path) -> int:
    return len(canonical_bytes(path))


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _legacy_mappings() -> dict[tuple[str, str], str]:
    if not ERRATUM.is_file():
        return {}
    document = json.loads(ERRATUM.read_text(encoding="utf-8"))
    mappings: dict[tuple[str, str], str] = {}
    for item in document.get("files", []):
        mappings[(str(item["path"]), str(item["historical_sha256"]))] = str(
            item["canonical_lf_sha256"]
        )
    for manifest in document.get("manifests", []):
        for item in manifest.get("references", []):
            key = (str(item["path"]), str(item["historical_sha256"]))
            canonical = str(item["canonical_lf_sha256"])
            if key in mappings and mappings[key] != canonical:
                raise ValueError(f"conflicting_evidence_portability_mapping:{key[0]}")
            mappings[key] = canonical
    return mappings


def matches_frozen_sha256(path: Path, expected: str, *, root: Path = ROOT) -> bool:
    """Accepte l'octet exact, le canonique futur ou un erratum EOL explicite."""
    expected = expected.casefold()
    if raw_sha256(path) == expected:
        return True
    canonical = canonical_sha256(path)
    if canonical == expected:
        return True
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    return _legacy_mappings().get((relative, expected)) == canonical


def matches_frozen_bytes(relative: str, payload: bytes, expected: str) -> bool:
    expected = expected.casefold()
    if hashlib.sha256(payload).hexdigest() == expected:
        return True
    canonical = hashlib.sha256(
        canonical_bytes_from_bytes(payload, suffix=Path(relative).suffix)
    ).hexdigest()
    if canonical == expected:
        return True
    return _legacy_mappings().get((Path(relative).as_posix(), expected)) == canonical


def matches_frozen_file(
    path: Path,
    *,
    expected_sha256: str,
    expected_bytes: int | None = None,
    root: Path = ROOT,
) -> bool:
    if not matches_frozen_sha256(path, expected_sha256, root=root):
        return False
    if expected_bytes is None or path.stat().st_size == expected_bytes:
        return True
    return canonical_size(path) == expected_bytes


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[1] != "verify":
        raise SystemExit("usage: evidence_portability.py verify PATH EXPECTED_SHA256")
    path = Path(sys.argv[2]).resolve()
    return 0 if matches_frozen_sha256(path, sys.argv[3]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
