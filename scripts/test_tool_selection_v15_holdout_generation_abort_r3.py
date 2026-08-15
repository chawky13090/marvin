"""Validate the immutable r3 abort and its aggregate-only diagnostic."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.5"
ABORT = BASE / "holdout-generation-abort-r3.json"
FORBIDDEN_KEYS = {"prompt", "prompts", "id", "candidate_id", "accepted_calls", "verdict", "raw_response", "content"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_private(value: object) -> None:
    if isinstance(value, dict):
        assert not (set(value) & FORBIDDEN_KEYS), set(value) & FORBIDDEN_KEYS
        for child in value.values():
            assert_private(child)
    elif isinstance(value, list):
        for child in value:
            assert_private(child)


def main() -> None:
    value = json.loads(ABORT.read_text(encoding="utf-8"))
    freeze = ROOT / value["freeze"]
    diagnostic = ROOT / value["diagnostic"]
    assert value["status"] == "aborted_without_public_holdout"
    assert value["reason_code"] == "critic_review_incomplete"
    assert value["failure_stage"] == "critic"
    assert value["freeze_sha256"] == sha(freeze)
    assert value["diagnostic_sha256"] == sha(diagnostic)
    assert value["authorization_consumed"] is True
    assert value["stage_b_authorized"] is False
    assert all(value[key] is False for key in ("corpus_written", "oracle_written", "report_written", "product_modified"))
    for name in ("holdout-corpus.json", "holdout-oracle.json", "holdout-generation-report.json"):
        assert not (BASE / name).exists(), name
    observed = json.loads(diagnostic.read_text(encoding="utf-8"))
    assert observed["status"] == "aborted"
    assert observed["failure_stage"] == "critic"
    assert observed["completed_stages"] == value["completed_stages"]
    assert observed["counts_by_intent"]["software.search"]["consensus_nonempty"] == 0
    assert observed["counts_by_intent"]["software.uninstall"]["oracle_a_nonempty"] == 0
    assert observed["counts_by_intent"]["software.install"]["consensus_nonempty"] == 20
    assert observed["aggregate_only"] is True
    assert_private(observed)
    print("Tool Selection v1.5 Holdout Abort r3 OK - critic incomplete, diagnostic preserved, Stage B locked")


if __name__ == "__main__":
    main()
