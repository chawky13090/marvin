"""Canaris et acceptation de l'analyseur statique des surfaces E7."""
from __future__ import annotations

import json
from pathlib import Path

from e7_surface_analyzer import (
    BASE,
    CONTRACTS_PATH,
    ROOT,
    RULES_PATH,
    ProjectIndex,
    analyze,
    analyze_contracts,
    verdict,
)

CANARIES = ROOT / "scripts" / "fixtures" / "e7_surface_analysis_canaries.py"


def main() -> int:
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    fixture_index = ProjectIndex([CANARIES], source_root=CANARIES.parent)

    positive = analyze(fixture_index, "e7_surface_analysis_canaries.sqlite_only", rules)
    assert positive.effects == {"sqlite"}, positive
    assert verdict(positive.effects, {"sqlite"}, bool(positive.unresolved)) == "CONFIRMED"

    negative = analyze(fixture_index, "e7_surface_analysis_canaries.pure_function", rules)
    assert negative.effects == set(), negative
    assert verdict(negative.effects, set(), bool(negative.unresolved)) == "CONFIRMED"

    ambiguous = analyze(fixture_index, "e7_surface_analysis_canaries.dynamic_dispatch", rules)
    assert ambiguous.effects == {"unknown"}, ambiguous
    assert verdict(ambiguous.effects, set(), bool(ambiguous.unresolved)) == "UNKNOWN"

    original_contract_hash = __import__("hashlib").sha256(CONTRACTS_PATH.read_bytes()).hexdigest()
    report = analyze_contracts()
    assert report["contracts"] == 22
    assert report["tool_execution_performed"] is False
    assert report["contract_mutation_performed"] is False
    assert all(".venv" not in path for path in report["source_hashes"])
    assert all((ROOT / path).is_file() for path in report["source_hashes"])
    assert __import__("hashlib").sha256(CONTRACTS_PATH.read_bytes()).hexdigest() == original_contract_hash
    note = next(item for item in report["results"] if item["tool"] == "note_delete")
    assert note["state"] == "UNDER_DECLARED", note
    assert {"sqlite", "qdrant"}.issubset(note["confirmed_effects"]), note
    joined_paths = "\n".join(" -> ".join(path) for path in note["paths"])
    for fragment in (
        "backend/tool_domains/productivity.py:note_delete",
        "backend/tool_domains/productivity.py:_delete_note_index",
        "sink:vector_store.delete_document",
    ):
        assert fragment in joined_paths, fragment
    analyzer_source = (ROOT / "scripts" / "e7_surface_analyzer.py").read_text(encoding="utf-8")
    assert "note_delete" not in analyzer_source
    print(f"E7 Surface Analyzer OK - 3 canaries, note_delete UNDER_DECLARED, {report['contracts']} contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
