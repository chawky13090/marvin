"""Offline canaries for the v1.5 r3 aggregate holdout diagnostics."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import generate_tool_selection_v15_holdout_r3 as runner


FORBIDDEN_KEYS = {
    "prompt", "prompts", "id", "candidate_id", "accepted_calls", "verdict",
    "raw_response", "content", "email", "name",
}


def assert_privacy(value: object) -> None:
    if isinstance(value, dict):
        assert not (set(value) & FORBIDDEN_KEYS), set(value) & FORBIDDEN_KEYS
        for child in value.values():
            assert_privacy(child)
    elif isinstance(value, list):
        for child in value:
            assert_privacy(child)


def main() -> None:
    counts = runner._empty_counts()
    first = next(iter(runner.INTENTS))
    counts[first].update({
        "authored_valid": 20,
        "oracle_a_nonempty": 18,
        "oracle_b_nonempty": 17,
        "consensus_nonempty": 14,
        "adjudicator_valid": 13,
        "critic_valid": 12,
        "both_reviews_valid": 11,
        "novelty_valid": 16,
        "survivors_final": 7,
    })
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        policy = root / "policy.json"
        policy.write_text("{}\n", encoding="utf-8", newline="\n")
        diagnostic = root / "diagnostic.json"
        with patch.object(runner, "POLICY", policy), patch.object(runner, "DIAGNOSTIC", diagnostic):
            complete = runner._write_diagnostic(
                counts=counts,
                completed_stages=["author", "oracle_a", "oracle_b", "consensus"],
                status="complete",
            )
            persisted = json.loads(diagnostic.read_text(encoding="utf-8"))
            assert persisted == complete
            assert persisted["counts_by_intent"][first] == counts[first]
            assert persisted["failure_stage"] is None
            assert persisted["failure_intent"] is None
            assert_privacy(persisted)

            diagnostic.unlink()
            try:
                runner._abort_insufficient(
                    first,
                    2,
                    5,
                    counts=counts,
                    completed_stages=["author", "oracle_a", "oracle_b", "consensus", "selection"],
                )
            except RuntimeError as exc:
                assert "2/5" in str(exc)
            else:
                raise AssertionError("Le canari d'insuffisance devait échouer.")
            assert diagnostic.exists(), "Le diagnostic doit précéder l'exception."
            aborted = json.loads(diagnostic.read_text(encoding="utf-8"))
            assert aborted["status"] == "aborted"
            assert aborted["failure_stage"] == "selection"
            assert aborted["failure_intent"] == first
            assert_privacy(aborted)

            try:
                runner._diagnostic(
                    counts=counts,
                    completed_stages=[],
                    status="aborted",
                    failure_stage=None,
                    failure_intent=None,
                )
            except ValueError:
                pass
            else:
                raise AssertionError("Un abandon sans étage ni intention doit être refusé.")

    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "v15-r3-{intent" in source
    assert "prompt_or_item_specific" not in source
    print("Tool Selection v1.5 Holdout Observability r3 OK - atomic, aggregate, privacy-safe, execution locked")


if __name__ == "__main__":
    main()
