"""Vérifie le holdout Stage B gelé avant tout appel au modèle évalué."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.2"
MANIFEST = BASE / "holdout-freeze-manifest.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    corpus = json.loads((BASE / "holdout-corpus.json").read_text(encoding="utf-8"))
    oracle = json.loads((BASE / "holdout-oracle.json").read_text(encoding="utf-8"))
    report = json.loads((BASE / "holdout-generation-report.json").read_text(encoding="utf-8"))
    policy = json.loads((BASE / "stage-b-preregistration.json").read_text(encoding="utf-8"))

    assert manifest["status"] == "frozen_before_benchmark_model_invocation"
    assert manifest["benchmark_model_invocation_count_before_freeze"] == 0
    assert manifest["business_tool_execution_count_before_freeze"] == 0
    assert manifest["next_phase"]["benchmark_model_execution_authorized"] is False
    assert manifest["next_phase"]["business_tool_execution_authorized"] is False
    for relative, expected in manifest["frozen_hashes"].items():
        path = ROOT / relative
        assert path.is_file(), relative
        assert sha256(path) == expected, relative
        assert "\r\n" not in path.read_text(encoding="utf-8"), relative

    items = corpus["items"]
    oracle_items = oracle["items"]
    assert corpus["status"] == oracle["status"] == "frozen_candidate"
    assert len(items) == len(oracle_items) == 30
    ids = [row["id"] for row in items]
    assert len(set(ids)) == 30
    assert set(ids) == {row["id"] for row in oracle_items}
    expected_families = policy["holdout"]["families"]
    assert Counter(row["family"] for row in items) == Counter(expected_families)
    assert all(expected_families[name] == 5 for name in expected_families)
    assert all(re.fullmatch(r"sb-[a-z-]+-\d{2}", row["id"]) for row in items)
    assert all(20 <= len(row["prompt"]) <= 600 for row in items)
    forbidden = (r"[A-Z]:\\Users\\(?!Fixture(?:\\|$))", r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", r"\\\\[^\\\s]+\\")
    assert all(not any(re.search(pattern, row["prompt"], re.I) for pattern in forbidden) for row in items)

    generator_path = ROOT / "scripts/generate_tool_selection_stage_b_holdout.py"
    spec = importlib.util.spec_from_file_location("stage_b_generator_frozen", generator_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    catalog = {str(item["function"]["name"]): item for item in module.TOOLS_SPEC}
    for row in oracle_items:
        calls = row["accepted_calls"]
        assert calls
        assert module._schema_valid_calls(calls, catalog) == calls

    assert report["policy_sha256"] == sha256(BASE / "stage-b-preregistration.json")
    assert report["generator_sha256"] == sha256(generator_path)
    assert report["corpus_sha256"] == sha256(BASE / "holdout-corpus.json")
    assert report["oracle_sha256"] == sha256(BASE / "holdout-oracle.json")
    assert report["counts"]["authored"] == 384
    assert report["counts"]["selected"] == 30
    assert report["counts"]["families"] == expected_families
    assert report["privacy"] == {
        "synthetic_only": True,
        "raw_model_responses_published": False,
        "personal_data_patterns_passed": True,
    }
    observed_models = {
        entry["requested_model"]
        for entries in report["models"].values()
        for entry in entries
    }
    benchmark_model = policy["independent_roles"]["benchmark"]["model"]
    assert benchmark_model not in observed_models
    for entries in report["models"].values():
        assert entries
        assert all(
            entry["requested_model"].replace("-cloud", "").removesuffix(":cloud") == entry["observed_model"]
            for entry in entries
        )
        assert all(entry["client_num_ctx"] is None for entry in entries)
        assert all(1 <= entry["attempts"] <= 3 for entry in entries)
        assert all("raw_response" not in entry for entry in entries)

    assert module._schema_valid_calls(
        [{"tool": "windows_task", "action": "not.real", "constraints": []}], catalog
    ) == []
    print("Stage B holdout freeze OK - 30 synthetic cases, independent oracle, benchmark unseen.")


if __name__ == "__main__":
    main()
