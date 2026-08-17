"""Vérifie la couverture et la précision de l'inventaire de données personnelles."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import privacy_inventory


def main() -> int:
    persistence = (ROOT / "MARVIN-PERSISTENCE-INVENTORY.md").read_text(encoding="utf-8")
    block = re.search(r"<!-- persistence-inventory\s*(.*?)\s*-->", persistence, re.S)
    assert block is not None
    expected = {
        (line.split("|")[0], line.split("|")[1])
        for line in block.group(1).splitlines()
        if line.strip() and len(line.split("|")) >= 2
    }
    actual = {(item.module, item.file_pattern) for item in privacy_inventory.STREAMS}
    assert actual == expected, {"missing": sorted(expected - actual), "extra": sorted(actual - expected)}
    assert len(actual) == len(privacy_inventory.STREAMS) == 16
    allowed_classes = {"indirect_identifier", "free_text", "public_reference", "technical_metadata", "network_identifier"}
    assert len(privacy_inventory.PERSONAL_STATE_STREAMS) == 2
    assert privacy_inventory.PERSONAL_STATE_STREAMS[0].file_pattern == "rollback/bulk-rename/*.json"
    assert privacy_inventory.PERSONAL_STATE_STREAMS[1].file_pattern == "ssh_known_hosts"
    for stream in privacy_inventory.STREAMS + privacy_inventory.PERSONAL_STATE_STREAMS:
        assert stream.data_class in allowed_classes
        assert stream.export_strategy
        assert stream.erasure_strategy
        if stream.data_class == "free_text":
            assert stream.content_fields
        if stream.erasure_strategy == "rechain_required":
            assert stream.subject_selectors
    public = privacy_inventory.public_inventory()
    assert len(public) == 18
    assert all("records" not in row and "values" not in row for row in public)
    print("Privacy inventory OK - 18/18 flux classifiés, sélecteurs et stratégie explicites.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
