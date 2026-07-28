"""Régressions du registre append-only de preuves métier."""

from __future__ import annotations

import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from durable_evidence_store import DurableEvidenceStore  # noqa: E402


def run() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "evidence.jsonl"
        legacy = {"id": "legacy-1", "created_at": "2026-01-01T00:00:00Z"}
        path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
        store = DurableEvidenceStore(path, stream_name="test.evidence")
        signed = store.append({"id": "signed-1", "success": True})
        assert signed["sequence"] == 2
        assert len(signed["record_hash"]) == 64
        assert len(signed["previous_hash"]) == 64
        integrity = store.verify()
        assert integrity["valid"] is True
        assert integrity["integrity_level"] == "mixed_legacy_unsigned"
        assert integrity["legacy_records"] == 1
        assert integrity["signed_records"] == 1
        assert integrity["retention"] == "owner_lifecycle"

        concurrent_path = root / "concurrent.jsonl"

        def append(index: int) -> dict:
            independent = DurableEvidenceStore(
                concurrent_path,
                stream_name="test.concurrent",
            )
            return independent.append({"id": f"record-{index}"})

        with ThreadPoolExecutor(max_workers=8) as pool:
            records = list(pool.map(append, range(100)))
        assert len({record["sequence"] for record in records}) == 100
        concurrent = DurableEvidenceStore(concurrent_path, stream_name="test.concurrent")
        concurrent_integrity = concurrent.verify()
        assert concurrent_integrity["valid"] is True
        assert concurrent_integrity["integrity_level"] == "tamper_evident"
        assert concurrent_integrity["signed_records"] == 100
        assert len(concurrent.recent(10)) == 10
        assert concurrent.recent(0) == []
        first_page = concurrent.page(after=0, limit=7)
        second_page = concurrent.page(after=first_page["cursor"], limit=7)
        assert [item["cursor"] for item in first_page["records"]] == list(range(1, 8))
        assert [item["cursor"] for item in second_page["records"]] == list(range(8, 15))
        assert first_page["cursor"] == 7 and second_page["cursor"] == 14

        unique_path = root / "unique.jsonl"

        def append_same_vote(index: int) -> bool:
            independent = DurableEvidenceStore(unique_path, stream_name="test.unique")
            try:
                independent.append_unique(
                    {"id": f"vote-{index}", "match_id": "match-1"},
                    unique_fields=("match_id",),
                )
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(append_same_vote, range(50)))
        assert outcomes.count(True) == 1
        unique = DurableEvidenceStore(unique_path, stream_name="test.unique")
        assert unique.verify()["integrity_level"] == "tamper_evident"
        assert unique.verify()["records"] == 1

        partial_path = root / "partial.jsonl"
        partial_store = DurableEvidenceStore(partial_path, stream_name="test.partial")
        partial_store.append({"id": "before-crash"})
        with partial_path.open("ab") as stream:
            stream.write(b'{"id":"incomplete"')
        repaired = partial_store.append({"id": "after-crash"})
        assert repaired["sequence"] == 2
        assert partial_store.verify()["valid"] is True
        quarantines = list(root.glob("partial.jsonl.partial.*"))
        assert len(quarantines) == 1
        assert quarantines[0].read_bytes() == b'{"id":"incomplete"'

        corrupt_path = root / "corrupt.jsonl"
        corrupt_path.write_text("{}\nnot-json\n", encoding="utf-8")
        corrupt_store = DurableEvidenceStore(corrupt_path, stream_name="test.corrupt")
        assert corrupt_store.verify()["valid"] is False
        try:
            corrupt_store.append({"id": "refused"})
        except RuntimeError:
            pass
        else:
            raise AssertionError("Une ligne corrompue complète doit bloquer l'ajout.")

        non_finite_path = root / "non-finite.jsonl"
        non_finite_path.write_text('{"score":NaN}\n', encoding="utf-8")
        non_finite = DurableEvidenceStore(non_finite_path, stream_name="test.non-finite")
        assert non_finite.verify()["valid"] is False
        try:
            non_finite.append({"id": "refused"})
        except RuntimeError:
            pass
        else:
            raise AssertionError("Une constante JSON non finie doit bloquer l'ajout.")

        tampered_rows = concurrent_path.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(tampered_rows[10])
        tampered["id"] = "altered"
        tampered_rows[10] = json.dumps(tampered)
        concurrent_path.write_text("\n".join(tampered_rows) + "\n", encoding="utf-8")
        detected = concurrent.verify()
        assert detected["valid"] is False
        assert any(error["reason"] == "record_hash" for error in detected["errors"])
        try:
            concurrent.append({"id": "must-not-extend-tampered-chain"})
        except RuntimeError:
            pass
        else:
            raise AssertionError("Une chaîne altérée ne doit jamais être prolongée.")

    print(
        "Durable Evidence Store OK - héritage, chaîne SHA-256, concurrence, "
        "crash partiel et altération."
    )


if __name__ == "__main__":
    run()
