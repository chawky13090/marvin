from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "benchmarks/chat-steering/v1/runtime-integration-result.json"
ACTIVATION = ROOT / "benchmarks/chat-steering/v1/activation-result.json"
AUTHORIZATION = ROOT / "benchmarks/chat-steering/v1/runtime-integration-authorization.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blob(commit: str, relative_path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def main() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["status"] == "offline_qualified_for_controlled_activation"
    assert result["authorization_sha256"] == sha256(AUTHORIZATION.read_bytes())
    commit = result["source_commit"]
    for relative_path, expected in result["governed_sources"].items():
        assert sha256(blob(commit, relative_path)) == expected, relative_path
    verified = result["verified"]
    assert all(value is True for key, value in verified.items() if isinstance(value, bool)), verified
    assert verified["frontend_production_build"] == "passed"
    assert verified["check_marvin"] == {
        "expected": 362,
        "executed": 357,
        "skipped_live": 5,
        "failed": 0,
    }
    assert result["controlled_activation_authorized"] is True
    assert result["release_verified"] is False
    assert all(result["activation_boundary"].values())
    activation = json.loads(ACTIVATION.read_text(encoding="utf-8"))
    assert activation["status"] == "verified_active"
    assert activation["version"] == "2.679.0"
    for relative_path, expected in activation["governed_sources"].items():
        assert sha256(blob(activation["source_commit"], relative_path)) == expected, relative_path
    observed = activation["observed"]
    assert observed["sqlite_migration_version"] == 7
    assert observed["cold_restarts"] >= 3
    assert observed["quick_gate"]["failed"] == 0
    assert observed["live_business_tool_calls"] == 0
    assert activation["data_integrity"]["user_conversations_deleted"] == 0
    print("Chat Turn Steering Runtime Result OK - offline proof and live activation frozen")


if __name__ == "__main__":
    main()
