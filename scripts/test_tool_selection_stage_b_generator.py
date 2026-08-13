"""Contrôle structurel du générateur Stage B avant son exécution Cloud."""
from __future__ import annotations
import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/generate_tool_selection_stage_b_holdout.py"

def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    assert "ablation-result.json" not in text
    assert "selected_tools" not in text and "stage_a_failures" not in text
    assert '"num_ctx" not in payload["options"]' in text
    assert "real_external_recipient" not in text
    assert "raw_response_sha256" in text and "raw_model_responses_published" in text
    assert "oracle_a" in text and "oracle_b" in text and "_consensus" in text
    assert "ADJUDICATOR_POLICY" in text and "_adjudications" in text
    assert "adjudicator_rejected" in text
    assert "CRITIC_POLICY" in text and "_schema_valid_calls" in text
    assert "critic_rejected" in text and "processus/service" in text
    assert "RELEVANT_PREFIXES" in text and "RELEVANT_EXACT" in text
    assert "for family_index, family in enumerate(ALLOWED_FAMILIES)" in text
    assert "family_counts = {name: 64 for name in ALLOWED_FAMILIES}" in text
    assert "minimum=64" in text
    assert "expected_family=family" in text
    assert "for attempt in range(1, 4)" in text and '"attempts": attempt' in text
    assert "family_ordinals" in text and "family_ordinals[family] += 1" in text
    assert '"prompt": prompt})' in text
    assert "private_details_published" in text and "_jaccard" in text
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert any(isinstance(call.func, ast.Name) and call.func.id == "_atomic" for call in calls)
    spec = importlib.util.spec_from_file_location("stage_b_generator_under_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module._adjudications({"items": [{"id": "a", "valid": True}]}, {"a", "b"}) == {"a": True, "b": False}
    assert module._adjudications({"items": [{"id": "a", "valid": True}, {"id": "a", "valid": True}]}, {"a"}) == {"a": False}
    assert module._adjudications({"items": [{"id": "a", "valid": "true"}]}, {"a"}) == {"a": False}
    print("Stage B generator OK - no Stage A labels, dual oracle, private novelty local only.")

if __name__ == "__main__":
    main()
