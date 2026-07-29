"""Régressions déterministes de la fondation de journalisation Marvin."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import audit  # noqa: E402
import bug_log  # noqa: E402
from structured_logging import StructuredJsonlStore, sanitize  # noqa: E402


def run() -> None:
    secret = "NE_DOIT_JAMAIS_ETRE_ECRIT"
    cleaned = sanitize(
        {
            "access_token": secret,
            "prompt": "contenu personnel",
            "nested": {"authorization": f"Bearer {secret}"},
            "error": f"token={secret}",
        }
    )
    serialized = json.dumps(cleaned, ensure_ascii=False)
    assert secret not in serialized
    assert cleaned["prompt"]["redacted"] is True
    assert len(cleaned["prompt"]["sha256"]) == 64
    runtime_config_source = (ROOT / "backend" / "api" / "runtime_config.py").read_text(
        encoding="utf-8"
    )
    assert 'body.get("confirmed") is not True' in runtime_config_source
    assert 'audit.log_action("audit_clear"' in runtime_config_source

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        clock = {"now": datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)}
        store = StructuredJsonlStore(
            root / "runtime.jsonl",
            component="test",
            retention_days=7,
            max_bytes=1024,
            max_archives=2,
            max_total_bytes=4096,
            clock=lambda: clock["now"],
        )
        for index in range(20):
            assert store.write(
                "test.event",
                trace_id=f"trace-{index}",
                attributes={"prompt": "x" * 200, "index": index},
            )
        archives = list(root.glob("runtime.*.jsonl"))
        assert 1 <= len(archives) <= 2
        recent = store.recent(5)
        assert len(recent) == 5
        assert recent[0]["trace_id"] == "trace-19"
        assert all(item["timestamp"].endswith("Z") for item in recent)
        assert all(item["schema_version"] == "1.0" for item in recent)

        concurrent_store = StructuredJsonlStore(
            root / "concurrent.jsonl",
            component="test.concurrent",
            max_bytes=1024 * 1024,
            clock=lambda: clock["now"],
        )
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(
                pool.map(
                    lambda index: concurrent_store.write(
                        "test.concurrent", trace_id=f"parallel-{index}"
                    ),
                    range(100),
                )
            )
        assert all(outcomes)
        concurrent_records = concurrent_store.recent(100)
        assert len(concurrent_records) == 100
        assert len({item["trace_id"] for item in concurrent_records}) == 100

        old = root / "runtime.20200101T000000000000Z.0001.jsonl"
        old.write_text("{}\n", encoding="utf-8")
        old_timestamp = (clock["now"] - timedelta(days=8)).timestamp()
        os.utime(old, (old_timestamp, old_timestamp))
        assert store.write("test.prune")
        assert not old.exists()
        daily = StructuredJsonlStore(
            root / "daily.jsonl",
            component="test.daily",
            max_bytes=1024 * 1024,
            clock=lambda: clock["now"],
        )
        assert daily.write("test.day-one")
        day_one_timestamp = clock["now"].timestamp()
        os.utime(daily.path, (day_one_timestamp, day_one_timestamp))
        clock["now"] += timedelta(days=1)
        assert daily.write("test.day-two")
        assert len(list(root.glob("daily.*.jsonl"))) == 1
        assert daily.recent(2)[0]["event_name"] == "test.day-two"
        unavailable = StructuredJsonlStore(root, component="unavailable")
        assert unavailable.write("test.failure") is False

        audit_path = root / "audit.jsonl"
        bug_path = root / "bug_log.jsonl"
        previous_audit_path = audit._AUDIT_PATH
        previous_bug_path = bug_log._BUG_LOG_PATH
        try:
            audit._AUDIT_PATH = str(audit_path)
            bug_log._BUG_LOG_PATH = str(bug_path)
            audit.log_action(
                "test_tool",
                {"prompt": "confidentiel", "password": secret, "safe": "ok"},
                {"success": True, "message": "terminé"},
                source="test",
                request_id="request-audit-1234",
            )
            actions = audit.recent(10)
            assert actions[0]["tool"] == "test_tool"
            assert actions[0]["source"] == "test"
            assert actions[0]["trace_id"] == "request-audit-1234"
            assert actions[0]["args"]["prompt"]["redacted"] is True
            assert actions[0]["result_message"]["redacted"] is True
            assert secret not in audit_path.read_text(encoding="utf-8")

            bug_log.log_bug(
                "test_exception",
                f"token={secret}",
                context={"email_body": "privé", "api_key": secret},
                traceback_str=f"RuntimeError: password={secret}",
                conversation_id="trace-test",
            )
            bugs = bug_log.recent(10)
            assert bugs[0]["kind"] == "test_exception"
            assert bugs[0]["trace_id"] == "trace-test"
            assert secret not in bug_path.read_text(encoding="utf-8")
            assert audit.clear() is True
            assert audit.recent(10) == []
        finally:
            audit._AUDIT_PATH = previous_audit_path
            bug_log._BUG_LOG_PATH = previous_bug_path
            audit._STORE = None
            audit._STORE_PATH = None
            bug_log._STORE = None
            bug_log._STORE_PATH = None

    print("Structured Logging OK - schéma, expurgation, rotation, rétention et compatibilité.")


if __name__ == "__main__":
    run()
