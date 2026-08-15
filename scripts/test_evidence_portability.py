"""Contrat inter-OS des preuves gelées et de leurs empreintes."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from evidence_portability import (
    ERRATUM,
    ROOT,
    canonical_bytes_from_bytes,
    canonical_sha256,
    matches_frozen_bytes,
    matches_frozen_sha256,
    raw_sha256,
)


HASH_MAP_KEYS = {
    "source_hashes", "frozen_hashes", "governed_source_hashes",
    "shared_production_source_hashes",
}


def _git_blob(path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f":{path}"], cwd=ROOT, check=True, capture_output=True
    ).stdout


def _git_blob_at(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=ROOT, check=True, capture_output=True
    ).stdout


def _hash_maps(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in HASH_MAP_KEYS and isinstance(child, dict):
                yield child
            yield from _hash_maps(child)
    elif isinstance(value, list):
        for child in value:
            yield from _hash_maps(child)


def main() -> int:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for rule in ("*.json text eol=lf", "*.py text eol=lf", "*.ps1 text eol=lf"):
        assert rule in attributes
    assert canonical_bytes_from_bytes(b"a\r\nb\r\n", suffix=".py") == b"a\nb\n"
    assert canonical_bytes_from_bytes(b"a\nb\n", suffix=".py") == b"a\nb\n"
    try:
        canonical_bytes_from_bytes(b"\xef\xbb\xbfa\n", suffix=".json")
    except ValueError:
        pass
    else:
        raise AssertionError("Le canari BOM n'a pas été rejeté.")

    document = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert document["schema"] == "marvin.evidence-line-ending-erratum/1.0"
    source_commit = document["source_commit"]
    subprocess.run(["git", "cat-file", "-e", f"{source_commit}^{{commit}}"], cwd=ROOT, check=True)
    assert document["hash_mode"] == "canonical_utf8_lf_v1"
    assert document["historical_manifests_modified"] is False
    assert document["semantic_content_changed"] is False
    assert document["manifest_count"] == 6
    assert document["reference_count"] == 50
    assert document["unique_path_count"] == 25
    assert document["normalized_file_count"] == 65

    explicit_mappings: dict[tuple[str, str], str] = {}
    for item in document["files"]:
        explicit_mappings[(item["path"], item["historical_sha256"])] = item["canonical_lf_sha256"]

    for item in document["files"]:
        path = ROOT / item["path"]
        assert path.read_bytes() == canonical_bytes_from_bytes(path.read_bytes(), suffix=path.suffix)
        historical_payload = _git_blob_at(source_commit, item["path"])
        historical_canonical = canonical_bytes_from_bytes(
            historical_payload, suffix=path.suffix
        )
        assert hashlib.sha256(historical_canonical).hexdigest() == item["canonical_lf_sha256"]
        assert matches_frozen_bytes(
            item["path"], historical_payload, item["historical_sha256"]
        )

    seen: dict[tuple[str, str], str] = {}
    for manifest in document["manifests"]:
        assert hashlib.sha256(_git_blob(manifest["path"])).hexdigest() == manifest["git_blob_sha256"]
        original = json.loads((ROOT / manifest["path"]).read_text(encoding="utf-8-sig"))
        serialized = json.dumps(original, ensure_ascii=False)
        for item in manifest["references"]:
            key = (item["path"], item["historical_sha256"])
            if key in seen:
                assert seen[key] == item["canonical_lf_sha256"]
            seen[key] = item["canonical_lf_sha256"]
            explicit_mappings[key] = item["canonical_lf_sha256"]
            assert item["historical_sha256"] in serialized
            historical_payload = _git_blob_at(source_commit, item["path"])
            historical_canonical = canonical_bytes_from_bytes(
                historical_payload, suffix=Path(item["path"]).suffix
            )
            assert hashlib.sha256(historical_canonical).hexdigest() == item["canonical_lf_sha256"]
            assert matches_frozen_bytes(
                item["path"], historical_payload, item["historical_sha256"]
            )

    tracked_json = subprocess.run(
        ["git", "ls-files", "benchmarks/**/*.json"], cwd=ROOT, check=True,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout.splitlines()
    assert tracked_json
    for relative in tracked_json:
        payload = _git_blob(relative)
        assert not payload.startswith(b"\xef\xbb\xbf"), relative
        assert b"\r" not in payload, relative
        current = ROOT / relative
        current_payload = current.read_bytes()
        assert current_payload == canonical_bytes_from_bytes(current_payload, suffix=current.suffix), relative
        parsed = json.loads(payload.decode("utf-8"))
        for mapping in _hash_maps(parsed):
            for source, expected in mapping.items():
                source = str(source).replace("\\", "/")
                target = ROOT / source
                if not target.is_file() or not isinstance(expected, str) or len(expected) != 64:
                    continue
                if raw_sha256(target) == expected.casefold() and canonical_sha256(target) != expected.casefold():
                    assert explicit_mappings.get((source, expected.casefold())) == canonical_sha256(target), (
                        f"new_machine_dependent_frozen_hash:{relative}:{source}"
                    )

    eol_rows = subprocess.run(
        ["git", "ls-files", "--eol", "benchmarks", "scripts", "backend"], cwd=ROOT,
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout.splitlines()
    noncanonical = [
        row for row in eol_rows
        if ("w/crlf" in row or "w/mixed" in row) and not row.casefold().endswith((".bat", ".cmd"))
    ]
    assert not noncanonical, noncanonical[:10]

    with tempfile.TemporaryDirectory(prefix="marvin-evidence-portability-") as temporary:
        altered = Path(temporary) / "agent.py"
        altered.write_text("semantic change\n", encoding="utf-8", newline="\n")
        historical = document["manifests"][0]["references"][0]["historical_sha256"]
        assert not matches_frozen_sha256(altered, historical, root=Path(temporary))

    print("Evidence Portability OK - 6 manifestes, 50 références, 25 sources canoniques")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
