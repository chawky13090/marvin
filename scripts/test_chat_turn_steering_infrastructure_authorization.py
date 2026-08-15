"""Validate the bounded authorization for the offline steering repository slice."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "benchmarks/chat-steering/v1/infrastructure-authorization.json"
PREREG = ROOT / "benchmarks/chat-steering/v1/preregistration.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _blob_sha(commit: str, relative: str) -> str:
    content = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(content).hexdigest()


def main() -> None:
    value = json.loads(AUTH.read_text(encoding="utf-8"))
    assert value["status"] == "authorized_offline_infrastructure_only"
    assert value["preregistration_sha256"] == _sha(PREREG)
    commit = value["preregistration_commit"]
    assert _blob_sha(commit, "benchmarks/chat-steering/v1/preregistration.json") == value["preregistration_sha256"]
    assert set(value["authorized_outputs"]) == {
        "backend/repositories/chat_turn_directives.py",
        "scripts/test_chat_turn_directives_repository.py",
    }
    assert all(value["forbidden_in_this_slice"].values())
    assert value["authorization_consumed"] is False
    assert len(value["required_negative_tests"]) >= 10
    for relative, expected in value["source_baseline_sha256"].items():
        assert _blob_sha(commit, relative) == expected, relative
    print("Chat Turn Steering Infrastructure Authorization OK - offline only, runtime locked")


if __name__ == "__main__":
    main()
