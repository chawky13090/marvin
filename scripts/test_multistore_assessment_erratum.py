"""Verrouille le défaut live v2.647 et la correction v2.648 avant rejeu."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.5"
ASSESSMENT = BASE / "multistore-correction-assessment.json"
SUPERSESSION = BASE / "direct-surface-supersession.json"
ERRATUM = BASE / "multistore-correction-assessment-erratum-v1.1.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _blob(commit: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, relative_path
    return result.stdout


def main() -> int:
    value = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert value["status"] == "published_before_corrected_runtime_replay"
    assert value["source_assessment_sha256"] == _sha256(ASSESSMENT)
    assert value["source_supersession_sha256"] == _sha256(SUPERSESSION)
    assert value["source_assessment_modified"] is False
    assert value["tool_execution_performed"] is False
    assert value["runtime_replay_authorized"] is True
    finding = value["finding"]
    assert finding["symbolic_warning"] == "qdrant_index:NameError"
    assert finding["e7_state"] == "UNVERIFIED"
    assert "hashlib" in finding["cause"]
    correction = value["correction"]
    commit = value["corrective_commit"]
    assert hashlib.sha256(_blob(commit, "backend/vector_store.py")).hexdigest() == (
        correction["vector_store_sha256"]
    )
    assert hashlib.sha256(_blob(commit, "scripts/test_note_lifecycle.py")).hexdigest() == (
        correction["test_sha256"]
    )
    acceptance = value["replay_acceptance"]
    assert acceptance["cold_restart_version"] == "2.648.0"
    assert acceptance["vm_status_reads"] == 5
    assert all(value["interpretation"].values())
    assert value["privacy"] == {
        "fixture_identifiers_published": False,
        "fixture_content_published": False,
        "user_data_used": False,
    }
    print("TD-014 Erratum OK - défaut live conservé, correction gelée, rejeu autorisé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
