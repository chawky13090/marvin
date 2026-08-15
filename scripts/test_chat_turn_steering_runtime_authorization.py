from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "benchmarks/chat-steering/v1/runtime-integration-authorization.json"
PREREG = ROOT / "benchmarks/chat-steering/v1/preregistration.json"
REPOSITORY = ROOT / "backend/repositories/chat_turn_directives.py"
REPOSITORY_TEST = ROOT / "scripts/test_chat_turn_directives_repository.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    authorization = json.loads(AUTH.read_text(encoding="utf-8"))
    preregistration = json.loads(PREREG.read_text(encoding="utf-8"))
    assert authorization["status"] == "authorized_behind_disabled_feature_flag"
    assert authorization["preregistration_sha256"] == sha256(PREREG)
    assert authorization["offline_repository_sha256"] == sha256(REPOSITORY)
    assert authorization["offline_repository_test_sha256"] == sha256(REPOSITORY_TEST)
    assert preregistration["activation"]["implementation_authorized"] is False
    constraints = authorization["activation_constraints"]
    assert constraints["feature_flag_default"] is False
    assert constraints["partial_backend_only_activation_forbidden"] is True
    assert constraints["runtime_activation_requires_separate_immutable_result"] is True
    invariants = authorization["mandatory_runtime_invariants"]
    assert all(invariants.values())
    forbidden = authorization["forbidden"]
    assert all(forbidden.values())
    evidence = set(authorization["required_delivery_evidence"])
    assert "approval_continuation_deadlock_canary" in evidence
    assert "full_check_marvin_gate" in evidence
    assert authorization["authorization_consumed"] is False
    print("Chat Turn Steering Runtime Authorization OK - integration allowed behind disabled flag")


if __name__ == "__main__":
    main()
