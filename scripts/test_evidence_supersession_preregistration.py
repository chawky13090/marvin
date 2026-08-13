"""Verrouille la gouvernance de supersession avant son implementation."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks" / "evidence-governance" / "v1" / "supersession-preregistration.json"


def main() -> int:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["status"] == "frozen_before_registry_implementation"
    assert policy["scope"]["historical_artifacts_are_immutable"] is True
    assert policy["scope"]["supersession_granularity"] == "subject"
    assert policy["scope"]["whole_file_supersession_is_forbidden_when_only_some_subjects_change"] is True
    invariants = policy["required_invariants"]
    assert all(invariants.values())
    assert policy["allowed_states"] == [
        "current", "superseded", "invalidated", "historical_only"
    ]
    execution = policy["execution"]
    assert not any(execution.values())
    assert policy["security_and_privacy"]["public_artifacts_may_contain_user_content"] is False
    assert policy["security_and_privacy"]["paths_are_repository_relative_only"] is True
    assert len(policy["known_transitions"]) == 4
    assert set(policy["authorized_outputs"]) == {
        "benchmarks/evidence-governance/v1/supersession-registry.json",
        "benchmarks/tool-evidence/v1.2/inventory.json",
    }
    print("Evidence Supersession Preregistration OK - sujets granulaires et preuves historiques immuables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
