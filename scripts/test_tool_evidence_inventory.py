"""Régressions de l'inventaire E0-E7 sans toucher à la base réelle."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from tool_evidence_inventory import DEFAULT_ACTION, build_inventory


def _fixture(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE messages (
          id TEXT PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT,
          tool_calls TEXT, tool_results TEXT, created_at TEXT
        );
        CREATE TABLE tool_executions (
          id TEXT PRIMARY KEY, tool_name TEXT, args TEXT, result TEXT,
          success INTEGER, duration_ms INTEGER, created_at TEXT,
          conversation_id TEXT, request_id TEXT
        );
        INSERT INTO conversations VALUES ('real', 'Réelle', '2026-01-01', '2026-01-01');
        INSERT INTO messages VALUES (
          'm1', 'real', 'user', 'liste les processus', NULL, NULL, '2026-01-01 10:00:00'
        );
        INSERT INTO tool_executions VALUES (
          'e1', 'windows_task', '{"action":"process.list"}', '{}', 1, 5,
          '2026-01-01 10:00:01', 'real', 'r1'
        );
        INSERT INTO tool_executions VALUES (
          'e2', 'windows_task', '{"action":"process.stop"}', '{}', 1, 5,
          '2026-01-01 10:00:02', 'deleted-benchmark', 'r2'
        );
        """
    )
    connection.commit()
    connection.close()


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "fixture.db"
        _fixture(database)
        report = build_inventory(database)
    assert report["summary"]["catalog_tools"] == 364
    assert report["database"]["mode"] == "read_only"
    items = {
        (item["tool"], item["action"]): item for item in report["items"]
    }
    listed = items[("windows_task", "process.list")]
    stopped = items[("windows_task", "process.stop")]
    assert listed["usage"]["distinct_human_message_count"] == 1
    assert listed["evidence"]["E6"] is True
    assert stopped["usage"]["orphan_or_ephemeral_executions"] == 1
    assert stopped["usage"]["distinct_human_message_count"] == 0
    assert stopped["evidence"]["E6"] is False
    assert stopped["evidence"]["E5"] is None
    assert stopped["evidence"]["E7"] is None
    assert report["summary"]["evidence_assessment_by_level"]["E5"] == {
        "verified": 0,
        "absent": 0,
        "unassessed": report["summary"]["tool_action_pairs"],
    }
    assert items[("file_find", DEFAULT_ACTION)]["llm_visible"] is True
    assert json.dumps(report, ensure_ascii=False)
    print("Tool Evidence Inventory OK - lecture seule, E0-E7 et exclusion éphémère.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
