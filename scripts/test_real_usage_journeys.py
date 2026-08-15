"""Contrat de l'analyse agrégée des parcours réels."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from real_usage_journeys import analyze  # noqa: E402


POLICY_PATH = ROOT / "benchmarks/real-usage-journeys/v1/preregistration.json"
POLICY = json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def seed(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE conversations (id TEXT PRIMARY KEY, created_at TEXT);
        CREATE TABLE messages (
          id TEXT, conversation_id TEXT, role TEXT, content TEXT,
          created_at TEXT, client_request_id TEXT
        );
        CREATE TABLE tool_executions (
          id TEXT, tool_name TEXT, success INTEGER, created_at TEXT,
          conversation_id TEXT, request_id TEXT, tool_call_id TEXT,
          app_version TEXT, model_name TEXT, runtime_mode TEXT,
          profile_name TEXT, selector_version TEXT, candidate_count INTEGER,
          candidate_set_sha256 TEXT, execution_source TEXT
        );
        """
    )
    conversations = [
        ("historical", "2026-08-14 10:00:00"),
        ("future-recovered", "2026-08-15 02:10:00"),
        ("future-abandoned", "2026-08-15 02:20:00"),
        ("future-next", "2026-08-15 02:30:00"),
        ("ephemeral", "2026-08-15 02:40:00"),
    ]
    connection.executemany("INSERT INTO conversations VALUES (?, ?)", conversations)
    messages = [
        ("m1", "historical", "user", "SECRET-HISTORICAL", "2026-08-14 10:00:00", "r1"),
        ("m2", "future-recovered", "user", "SECRET-FUTURE", "2026-08-15 02:10:00", "r2"),
        ("m3", "future-abandoned", "user", "SECRET-ABANDON", "2026-08-15 02:20:00", "r3"),
        ("m4", "future-next", "user", "SECRET-NEXT", "2026-08-15 02:30:00", "r4"),
    ]
    connection.executemany("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)", messages)
    full = ("2.660.0", "model", "eco", "normal", "selector/v1", 18, "a" * 64, "agent")
    executions = [
        ("e1", "old", 1, "2026-08-14 10:00:01", "historical", "r1", None, None, None, None, None, None, None, None, None),
        ("e2", "first", 0, "2026-08-15 02:10:01", "future-recovered", "r2", "tc2", *full),
        ("e3", "second", 1, "2026-08-15 02:10:02", "future-recovered", "r2", "tc3", *full),
        ("e4", "last", 0, "2026-08-15 02:20:01", "future-abandoned", "r3", "tc4", *full),
        ("e5", "orphan", 0, "2026-08-15 02:40:01", "ephemeral", "missing", "tc5", *full),
    ]
    connection.executemany(
        "INSERT INTO tool_executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        executions,
    )
    connection.commit()
    connection.close()


with tempfile.TemporaryDirectory() as folder:
    database = Path(folder) / "test.db"
    seed(database)
    result = analyze(database, POLICY)

encoded = json.dumps(result, ensure_ascii=False)
assert "SECRET" not in encoded
assert "r1" not in encoded and "m1" not in encoded
historical = result["splits"]["historical_development"]
future = result["splits"]["future_validation_eligible"]
incomplete = result["splits"]["future_unassessed_incomplete_metadata"]
assert historical["request_count"] == 1
assert incomplete["request_count"] == 1
assert incomplete["request_status"]["no_tool_execution"] == 1
assert future["request_count"] == 2
assert future["execution_count"] == 3
assert future["technical_recovery_request_count"] == 1
assert future["terminal_technical_failure_request_count"] == 1
assert future["probable_abandonment_signal_count"] == 1
assert future["exact_tool_call_correlation_request_count"] == 2
assert result["future_validation_requests_by_app_version"] == {"2.660.0": 2}
assert result["semantics"]["business_satisfaction"] == "UNASSESSED"
assert result["semantics"]["probable_abandonment_is_not_proof"] is True
assert len(result["aggregate_sha256"]) == 64

manifest_path = ROOT / "benchmarks/real-usage-journeys/v1/freeze-manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
assert manifest["future_validation_start_utc"] == POLICY["future_validation_start_utc"]
assert manifest["product_mutation_authorized"] is False
assert manifest["routing_mutation_authorized"] is False
for relative, expected in manifest["files"].items():
    raw = (ROOT / relative).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    assert hashlib.sha256(raw).hexdigest() == expected

historical = json.loads(
    (ROOT / "benchmarks/real-usage-journeys/v1/historical-baseline.json").read_text(
        encoding="utf-8"
    )
)
assert historical["splits"]["future_validation_eligible"]["request_count"] == 0
assert historical["semantics"]["historical_split_must_not_score_current_marvin"] is True

source = (ROOT / "scripts/real_usage_journeys.py").read_text(encoding="utf-8")
for forbidden in ("known_tool", "winget_install", "pc_app_launch", "SECRET"):
    assert forbidden not in source

print("Real usage journeys OK - exact joins, future split, privacy and uncertainty")
