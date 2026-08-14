"""Vérifie le gel du générateur et l'indépendance du holdout v1.3."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.3"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _blob(commit: str, relative: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def main() -> None:
    policy = json.loads((BASE / "holdout-generation-freeze.json").read_text(encoding="utf-8"))
    assert policy["status"] == "frozen_before_cloud_generation"
    assert policy["target_per_family"] >= 10
    assert policy["authorization"]["product_activation"] is False
    assert policy["authorization"]["business_tool_execution"] is False
    assert policy["privacy_security"]["client_num_ctx_forbidden"] is True
    assert policy["generator_sha256"] == _sha(ROOT / "scripts/generate_tool_selection_v13_holdout.py")
    assert len({row["model"].split(":", 1)[0] for row in policy["roles"].values()}) == 5
    benchmark = policy["benchmark_model_excluded_from_generation"]["model"]
    assert all(row["model"] != benchmark for row in policy["roles"].values())
    source_commit = policy["source_commit"]
    for relative, expected in policy["frozen_product_sources_sha256"].items():
        assert hashlib.sha256(_blob(source_commit, relative)).hexdigest() == expected, relative
    generator = (ROOT / "scripts/generate_tool_selection_v13_holdout.py").read_text(encoding="utf-8")
    assert "tool_canonical_facade" not in generator
    assert "stage-b-b1-result" not in generator
    assert re.search(r'["\']num_ctx["\']\s*:', generator) is None
    print("Tool selection v1.3 holdout freeze OK - five independent Cloud roles, no execution.")


if __name__ == "__main__":
    main()
