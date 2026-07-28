"""Régressions Memory Mesh et Truth Ledger avec stockage temporaire."""
from __future__ import annotations

import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import cortex
import memory_mesh
import truth_ledger


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        old_mesh = memory_mesh.MESH_PATH
        old_ledger = truth_ledger.LEDGER_PATH
        try:
            memory_mesh.MESH_PATH = root / "mesh.json"
            truth_ledger.LEDGER_PATH = root / "ledger.jsonl"
            truth_ledger.LEDGER_PATH.write_text(
                json.dumps({
                    "id": "0" * 32,
                    "conversation_id": "conv-legacy",
                    "created_at": "2026-07-01T00:00:00+00:00",
                    "claims": [],
                    "claim_count": 0,
                    "sourced_count": 0,
                    "unsupported_count": 0,
                }) + "\n",
                encoding="utf-8",
            )

            procedural = memory_mesh.register(1, "Etape 1 : lancer la commande puis vérifier le service", "procedure")
            semantic = memory_mesh.register(2, "Chaouki préfère des réponses courtes", "preference")
            assert procedural["kind"] == "procedural"
            assert semantic["kind"] == "semantic"
            assert memory_mesh.mark_used(1)["use_count"] == 1
            assert memory_mesh.stats()["by_kind"]["procedural"] == 1

            record = truth_ledger.record_response(
                conversation_id="conv-test",
                answer="La documentation officielle confirme ce comportement [doc]. "
                       "Une autre conclusion reste à vérifier.",
                citations=["https://example.test/doc"],
                evidence_tools=["web_deep_research"],
                reviewed=True,
                sources=[{
                    "citation": "doc",
                    "url": "https://example.test/doc",
                    "title": "Documentation officielle",
                    "excerpt": "Ce comportement est confirmé.",
                }],
            )
            assert record["claim_count"] == 2
            assert record["sourced_count"] == 1
            assert record["epistemic_debt"]["score"] > 0
            assert record["sequence"] == 2 and len(record["record_hash"]) == 64
            assert truth_ledger.list_records(conversation_id="conv-test")[0]["id"] == record["id"]
            integrity = truth_ledger.evidence_integrity()
            assert integrity["valid"] is True
            assert integrity["integrity_level"] == "mixed_legacy_unsigned"
            assert integrity["legacy_records"] == 1 and integrity["signed_records"] == 1

            def record_concurrently(index: int) -> int:
                result = truth_ledger.record_response(
                    conversation_id=f"conv-{index}",
                    answer=f"Cette affirmation concurrente numéro {index} reste sans source.",
                    citations=[],
                    evidence_tools=[],
                    reviewed=False,
                )
                return int(result["sequence"])

            with ThreadPoolExecutor(max_workers=8) as pool:
                sequences = list(pool.map(record_concurrently, range(20)))
            assert len(set(sequences)) == 20
            assert truth_ledger.evidence_integrity()["records"] == 22

            invalid_cases = (
                {"conversation_id": "../escape", "answer": "Réponse valide."},
                {"conversation_id": "conv-safe", "answer": "x" * 200_001},
                {
                    "conversation_id": "conv-safe",
                    "answer": "Une preuve dangereuse est refusée.",
                    "sources": [{"url": "javascript:alert(1)"}],
                },
                {
                    "conversation_id": "conv-safe",
                    "answer": "Une preuve avec secret est refusée.",
                    "sources": [{"url": "https://user:secret@example.test/doc"}],
                },
                {
                    "conversation_id": "conv-safe",
                    "answer": "Un port privé est refusé.",
                    "sources": [{"url": "https://example.test:8443/doc"}],
                },
            )
            for invalid in invalid_cases:
                try:
                    truth_ledger.record_response(
                        citations=[],
                        evidence_tools=[],
                        reviewed=False,
                        **invalid,
                    )
                except ValueError:
                    pass
                else:
                    raise AssertionError(f"Entrée Truth Ledger dangereuse acceptée : {invalid}")

            lines = truth_ledger.LEDGER_PATH.read_text(encoding="utf-8").splitlines()
            altered = json.loads(lines[-1])
            altered["claim_count"] = 999
            lines[-1] = json.dumps(altered, ensure_ascii=False)
            truth_ledger.LEDGER_PATH.write_text(
                "\n".join(lines) + "\n",
                encoding="utf-8",
            )
            assert truth_ledger.evidence_integrity()["valid"] is False
            try:
                truth_ledger.list_records(limit=10)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Une lecture Truth Ledger altérée doit échouer fermée.")
            try:
                truth_ledger.record_response(
                    conversation_id="conv-blocked",
                    answer="Cette nouvelle preuve doit être refusée.",
                    citations=[],
                    evidence_tools=[],
                    reviewed=False,
                )
            except RuntimeError:
                pass
            else:
                raise AssertionError("Un Truth Ledger altéré ne doit plus être prolongé.")

            truth_ledger.LEDGER_PATH.write_text(
                json.dumps({
                    "id": "f" * 32,
                    "conversation_id": "conv-malformed",
                    "created_at": "2026-07-01T00:00:00+00:00",
                    "claims": "not-a-list",
                    "claim_count": 0,
                    "sourced_count": 0,
                    "unsupported_count": 0,
                }) + "\n",
                encoding="utf-8",
            )
            malformed_integrity = truth_ledger.evidence_integrity()
            assert malformed_integrity["valid"] is False
            assert malformed_integrity["errors"] == [
                {"sequence": 1, "reason": "record_schema"}
            ]
        finally:
            memory_mesh.MESH_PATH = old_mesh
            truth_ledger.LEDGER_PATH = old_ledger

    compiled = cortex.compile_contract("Explique cette décision.")
    with (
        patch("truth_ledger.record_response", side_effect=RuntimeError("contenu sensible")),
        patch.object(cortex.bug_log, "log_bug") as log_bug,
    ):
        provenance = cortex.provenance(
            compiled,
            "qwen2.5:14b",
            [],
            answer="Cette réponse devrait produire une preuve.",
            conversation_id="conv-safe",
        )
    assert provenance["truth_ledger"]["evidence_persisted"] is False
    assert provenance["truth_ledger"]["error_type"] == "RuntimeError"
    assert "contenu sensible" not in str(log_bug.call_args)

    print("Knowledge Mesh OK - mémoires typées, usage et registre de vérité.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
