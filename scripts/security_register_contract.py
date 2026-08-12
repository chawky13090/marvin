"""Contrat machine du registre de dette de sécurité de Marvin."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "SECURITY-DEBT-REGISTER.md"
POLICY = ROOT / "benchmarks" / "security" / "security-register-reverification-policy-v1.json"
TECHNICAL_DEBT = ROOT / "docs" / "TECHNICAL-DEBT.md"
POLICY_SHA256 = "2b4d3c3284ba04af1c3f22917b098b23703d0498632a443ce6485ce918787f9a"
ALLOWED_STATUSES = {"OPEN", "MITIGATED", "VERIFIED", "ACCEPTED", "UNKNOWN"}
HIGH_SEVERITIES = {"Critique", "Élevée"}
EMPTY = {"", "-", "—"}


class SecurityRegisterError(RuntimeError):
    pass


@dataclass(frozen=True)
class Entry:
    identifier: str
    severity: str
    historical_status: str
    reverified_status: str
    reason: str
    commit: str
    tests: tuple[str, ...]
    rollback: str
    runtime_evidence: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(text: str, header: str) -> list[list[str]]:
    lines = text.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.startswith(header))
    except StopIteration as exc:
        raise SecurityRegisterError(f"security_register_table_missing:{header}") from exc
    rows: list[list[str]] = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def parse_register(text: str) -> list[Entry]:
    historical_rows = _rows(text, "| ID | Sévérité | État historique déclaré |")
    current_rows = _rows(text, "| ID | État réévalué |")
    historical: dict[str, tuple[str, str]] = {}
    for row in historical_rows:
        if len(row) != 5 or row[0] in historical:
            raise SecurityRegisterError("security_register_historical_row_invalid")
        historical[row[0]] = (row[1], row[2])
    current: dict[str, list[str]] = {}
    for row in current_rows:
        if len(row) != 7 or row[0] in current:
            raise SecurityRegisterError("security_register_reverified_row_invalid")
        current[row[0]] = row
    if set(historical) != set(current):
        raise SecurityRegisterError("security_register_tables_diverge")
    entries: list[Entry] = []
    for identifier, (severity, historical_status) in historical.items():
        row = current[identifier]
        tests = tuple(item.strip() for item in row[4].split("<br>") if item.strip() not in EMPTY)
        entries.append(Entry(
            identifier=identifier,
            severity=severity,
            historical_status=historical_status,
            reverified_status=row[1],
            reason=row[2],
            commit=row[3],
            tests=tests,
            rollback=row[5],
            runtime_evidence=row[6],
        ))
    return entries


def _git_commit_exists(value: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{7,40}", value):
        return False
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{value}^{{commit}}"],
        cwd=ROOT, capture_output=True, text=True, errors="replace", check=False,
    )
    return completed.returncode == 0


def validate_entries(entries: list[Entry], *, check_git: bool = True) -> Counter[str]:
    expected = [f"SEC-{number:03d}" for number in range(1, 25)]
    identifiers = [entry.identifier for entry in entries]
    if identifiers != expected:
        raise SecurityRegisterError("security_register_ids_not_contiguous")
    for entry in entries:
        if entry.historical_status not in ALLOWED_STATUSES - {"UNKNOWN"}:
            raise SecurityRegisterError(f"historical_status_invalid:{entry.identifier}")
        if entry.reverified_status not in ALLOWED_STATUSES:
            raise SecurityRegisterError(f"reverified_status_invalid:{entry.identifier}")
        if not entry.reason or entry.reason in EMPTY:
            raise SecurityRegisterError(f"verification_reason_missing:{entry.identifier}")
        if entry.reverified_status != "VERIFIED":
            continue
        if entry.commit in EMPTY or (check_git and not _git_commit_exists(entry.commit)):
            raise SecurityRegisterError(f"verified_commit_missing:{entry.identifier}")
        if not entry.tests or any(not (ROOT / test).is_file() for test in entry.tests):
            raise SecurityRegisterError(f"verified_test_missing:{entry.identifier}")
        if entry.rollback in EMPTY:
            raise SecurityRegisterError(f"verified_rollback_missing:{entry.identifier}")
        if entry.severity in HIGH_SEVERITIES:
            if entry.runtime_evidence in EMPTY or not (ROOT / entry.runtime_evidence).is_file():
                raise SecurityRegisterError(f"verified_runtime_evidence_missing:{entry.identifier}")
    return Counter(entry.reverified_status for entry in entries)


def summary(counts: Counter[str]) -> str:
    return (
        "SECURITY_REGISTER_SUMMARY: "
        f"VERIFIED={counts['VERIFIED']}; MITIGATED={counts['MITIGATED']}; "
        f"UNKNOWN={counts['UNKNOWN']}; OPEN={counts['OPEN']}; ACCEPTED={counts['ACCEPTED']}"
    )


def run() -> dict[str, object]:
    if _sha256(POLICY) != POLICY_SHA256:
        raise SecurityRegisterError("security_policy_hash_mismatch")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if policy["execution_authorized"] or policy["persistent_data_mutation_authorized"]:
        raise SecurityRegisterError("security_policy_execution_not_locked")
    entries = parse_register(REGISTER.read_text(encoding="utf-8-sig"))
    counts = validate_entries(entries)
    expected_summary = summary(counts)
    register_text = REGISTER.read_text(encoding="utf-8-sig")
    debt_text = TECHNICAL_DEBT.read_text(encoding="utf-8-sig")
    if register_text.count(expected_summary) != 1:
        raise SecurityRegisterError("security_register_summary_not_derived")
    if debt_text.count(expected_summary) != 1:
        raise SecurityRegisterError("td_007_summary_not_derived")
    return {"entries": len(entries), "counts": dict(counts), "summary": expected_summary}
