"""Fail closed when a planned Marvin shutdown would interrupt active work."""
from __future__ import annotations
import json
import sqlite3
import sys
import time
from pathlib import Path

database = Path(__file__).resolve().parents[1] / "data" / "secretary.db"
result = {"running_turns": 0, "pending_approvals": 0, "active": False}
if database.is_file():
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True, timeout=2)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "chat_turns" in tables:
            result["running_turns"] = int(connection.execute("SELECT COUNT(*) FROM chat_turns WHERE status='running'").fetchone()[0])
        if "tool_approval_requests" in tables:
            result["pending_approvals"] = int(connection.execute("SELECT COUNT(*) FROM tool_approval_requests WHERE status='pending' AND expires_at > ?", (time.time(),)).fetchone()[0])
    finally:
        connection.close()
result["active"] = bool(result["running_turns"] or result["pending_approvals"])
print(json.dumps(result, separators=(",", ":")))
sys.exit(3 if result["active"] else 0)
