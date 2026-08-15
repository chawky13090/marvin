"""Validate v1.5 holdout generation freeze before and after its single use."""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.5"
FREEZE = BASE / "holdout-generation-freeze.json"
FREEZE_COMMIT = "48b06ba2f37fabb5e4541cf1326ef514a5228804"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git_blob_sha(commit: str, path: str) -> str:
    value = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(value).hexdigest()

def main() -> None:
    value = json.loads(FREEZE.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_before_cloud_generation"
    assert sha(ROOT / "scripts/generate_tool_selection_v15_holdout.py") == value["generator_sha256"]
    assert sha(BASE / "software-intent-boundary-preregistration.json") == value["preregistration_sha256"]
    assert len(value["intents"]) == 7 and value["target_per_intent"] == 5
    assert len({row["model"].split(":")[0] for row in value["roles"].values()}) == 5
    for relative, expected in value["frozen_product_sources_sha256"].items():
        assert git_blob_sha(FREEZE_COMMIT, relative) == expected, relative
    assert value["authorization"]["business_tool_execution"] is False
    assert value["authorization"]["host_side_effects"] is False
    print("Tool Selection v1.5 Holdout Generation Freeze OK - intents=7 target=35")

if __name__ == "__main__":
    main()
