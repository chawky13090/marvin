"""Validate the published, development-only v1.5 Stage A measurement."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.5"
CORPUS = BASE / "development-corpus.json"
POLICY = BASE / "software-intent-boundary-preregistration.json"
RESULT = BASE / "development-stage-a-result.json"
SOURCE = ROOT / "backend/agent_tool_selection.py"
SOURCE_COMMIT = "48b06ba2f37fabb5e4541cf1326ef514a5228804"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_blob_sha(commit: str, path: str) -> str:
    value = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert corpus["status"] == "development_only_never_release_holdout"
    assert len(corpus["items"]) == 40
    assert result["status"] == "development_evidence_not_release_validation"
    assert result["corpus_sha256"] == _sha(CORPUS)
    assert result["product_source_sha256"] == _git_blob_sha(
        SOURCE_COMMIT, SOURCE.relative_to(ROOT).as_posix()
    )
    assert result["preregistration_sha256"] == _sha(POLICY)
    assert result["business_tool_execution_count"] == 0
    assert result["host_side_effect_count"] == 0
    assert result["benchmark_model_call_count"] == 0
    for mode, configurations in result["summaries"].items():
        assert configurations["K+L+S"]["candidate_recall"] == 1.0, mode
        for name, summary in configurations.items():
            assert summary["forbidden_mutation_count"] == 0, (mode, name)
    assert any("not usable for release" in item for item in result["limitations"])
    print("Tool Selection v1.5 Development Stage A OK - rows=1120 release_claim=false")


if __name__ == "__main__":
    main()
