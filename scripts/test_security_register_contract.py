"""Tests positifs et négatifs du registre de sécurité réévalué."""
from __future__ import annotations

from dataclasses import replace

from security_register_contract import ROOT, SecurityRegisterError, parse_register, run, validate_entries


def denied(entries, identifier: str, **updates) -> None:
    candidate = [replace(entry, **updates) if entry.identifier == identifier else entry for entry in entries]
    try:
        validate_entries(candidate, check_git=False)
    except SecurityRegisterError:
        return
    raise AssertionError(f"security_negative_canary_not_denied:{identifier}:{sorted(updates)}")


def main() -> int:
    result = run()
    entries = parse_register((ROOT / "SECURITY-DEBT-REGISTER.md").read_text(encoding="utf-8-sig"))
    base = next(entry for entry in entries if entry.identifier == "SEC-002")
    complete = replace(
        base,
        reverified_status="VERIFIED",
        reason="positive_canary",
        commit="4472b3a",
        tests=("scripts/test_security_register_contract.py",),
        rollback="revert positive canary fixture",
        runtime_evidence="benchmarks/tool-evidence/v1.2/e7-apply-replay-result.json",
    )
    validate_entries([complete if entry.identifier == "SEC-002" else entry for entry in entries])
    denied(entries, "SEC-002", reverified_status="VERIFIED", reason="missing_all_evidence")
    denied(
        entries,
        "SEC-002",
        reverified_status="VERIFIED",
        reason="missing_commit",
        tests=("scripts/test_security_register_contract.py",),
        rollback="x",
        runtime_evidence="benchmarks/tool-evidence/v1.2/e7-apply-replay-result.json",
    )
    denied(entries, "SEC-002", reverified_status="VERIFIED", reason="missing_test", commit="4472b3a", rollback="x", runtime_evidence="benchmarks/tool-evidence/v1.2/e7-apply-replay-result.json")
    denied(entries, "SEC-002", reverified_status="VERIFIED", reason="missing_rollback", commit="4472b3a", tests=("scripts/test_security_register_contract.py",), runtime_evidence="benchmarks/tool-evidence/v1.2/e7-apply-replay-result.json")
    denied(entries, "SEC-002", reverified_status="VERIFIED", reason="missing_runtime", commit="4472b3a", tests=("scripts/test_security_register_contract.py",), rollback="x")
    print(f"Security register contract OK - {result['entries']} entries; {result['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
