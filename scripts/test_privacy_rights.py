"""Tests de l'export personnel exact, chiffré et sans fuite de sélecteur."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from durable_evidence_store import DurableEvidenceStore
from portable_backup_encryption import decrypt_file
from privacy_rights import ExportTarget, PrivacyRightsError, create_export


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="marvin-privacy-") as directory:
        root = Path(directory)
        store = DurableEvidenceStore(root / "proofs.jsonl", stream_name="test.privacy")
        store.append({"id": "one", "conversation_id": "conv-private", "claims": [{"id": "claim-1", "claim": "Alice"}]})
        store.append({"id": "two", "conversation_id": "conv-other", "claims": [{"id": "claim-2", "claim": "Bob"}]})
        targets = {"truth": ExportTarget("truth", ("id", "conversation_id", "claims[].id"), lambda: store)}
        events: list[tuple[str, dict]] = []
        destination = root / "export.mrvprivacy"
        result = create_export("truth", "conversation_id", "conv-private", destination, passphrase="correct horse battery", event_logger=lambda event, attrs: events.append((event, attrs)), targets=targets)
        assert result["records"] == 1 and result["integrity_verified"] is True
        plain = root / "plain.json"
        decrypt_file(destination, plain, passphrase="correct horse battery")
        payload = json.loads(plain.read_text(encoding="utf-8"))
        assert [row["id"] for row in payload["records"]] == ["one"]
        assert store.verify()["records"] == 2
        assert "conv-private" not in str(events)
        try:
            create_export("truth", "claims[].claim", "Alice", root / "forbidden.mrvprivacy", passphrase="correct horse battery", targets=targets)
        except PrivacyRightsError:
            pass
        else:
            raise AssertionError("Un sélecteur libre non déclaré doit être refusé.")
    print("Privacy rights OK - sélection exacte, export chiffré vérifié et source intacte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
