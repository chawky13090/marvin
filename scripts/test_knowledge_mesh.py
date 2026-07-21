"""Régressions Memory Mesh et Truth Ledger avec stockage temporaire."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

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
            assert truth_ledger.list_records(conversation_id="conv-test")[0]["id"] == record["id"]
        finally:
            memory_mesh.MESH_PATH = old_mesh
            truth_ledger.LEDGER_PATH = old_ledger

    print("Knowledge Mesh OK - mémoires typées, usage et registre de vérité.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
