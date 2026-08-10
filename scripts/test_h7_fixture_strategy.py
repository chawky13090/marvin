"""Contrat du gel des strates E7 et de la certification de harnais H7."""

from __future__ import annotations

import hashlib
import json

from h7_fixture_strategy_freeze import BASE, ROOT, validate


def main() -> int:
    summary = validate()
    assert summary == {
        "classified_pairs": 36,
        "direct_fixture_pairs": 22,
        "bounded_polymorphic_pairs": 6,
        "arbitrary_executor_pairs": 8,
        "h7_abstract_cases": 30,
        "tool_execution_authorized": False,
        "h7_sets_e7": False,
    }
    manifest = json.loads(
        (BASE / "h7-fixture-strategy-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "frozen_before_fixture_or_harness_execution"
    assert manifest["fixture_design_authorized"] is True
    assert manifest["tool_execution_authorized"] is False
    for relative, expected in manifest["source_hashes"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
    print("H7/E7 Strategy Freeze OK - 22 directs, 6 P bornés, 8 H7, 30 cas symboliques.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
