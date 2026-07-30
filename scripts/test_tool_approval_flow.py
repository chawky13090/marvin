"""Contrats des approbations d'outils et de l'autonomie temporaire."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import agent_autonomy
from repositories.tool_approvals import ToolApprovalRepository


class Settings:
    def __init__(self) -> None:
        self.values: dict = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "approvals.db"

        @contextmanager
        def scope():
            connection = sqlite3.connect(path)
            connection.row_factory = sqlite3.Row
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

        repository = ToolApprovalRepository(scope)
        first = repository.create_or_reuse(
            call_digest="a" * 64,
            tool_name="winget_install",
            arguments={"id": "VideoLAN.VLC"},
            conversation_id="conversation-1",
            request_id="request-1",
            source="chat",
            risk_tier=3,
        )
        reused = repository.create_or_reuse(
            call_digest="a" * 64,
            tool_name="winget_install",
            arguments={"id": "VideoLAN.VLC"},
            conversation_id="conversation-1",
            request_id="request-1",
            source="chat",
            risk_tier=3,
        )
        assert reused["id"] == first["id"]
        claimed = repository.claim(first["id"])
        assert claimed and claimed["status"] == "executing" and claimed["claimed"]
        duplicate = repository.claim(first["id"])
        assert duplicate and duplicate["status"] == "executing"
        assert not duplicate["claimed"]
        finished = repository.finish(first["id"], approved=True, reason="executed")
        assert finished and finished["status"] == "approved"
        assert finished["arguments"] == {}
        final_replay = repository.claim(first["id"])
        assert final_replay and final_replay["status"] == "approved"

        denied = repository.create_or_reuse(
            call_digest="b" * 64,
            tool_name="file_delete",
            arguments={"path": "C:/temp/test.txt"},
            conversation_id="conversation-1",
            request_id="request-2",
            source="chat",
            risk_tier=5,
        )
        denied = repository.deny(denied["id"])
        assert denied and denied["status"] == "denied"
        assert denied["arguments"] == {}

    settings = Settings()
    with patch.object(agent_autonomy.audit, "log_action") as audit_log:
        assert agent_autonomy.current(settings)["mode"] == "normal"
        auto = agent_autonomy.configure(settings, "auto", 60)
        assert auto["active"] and auto["mode"] == "auto"
        assert agent_autonomy.allows("auto", 3)
        assert not agent_autonomy.allows("auto", 4)
        full = agent_autonomy.configure(settings, "full", 60)
        assert full["active"] and agent_autonomy.allows("full", 5)
        normal = agent_autonomy.configure(settings, "normal", 60)
        assert not normal["active"]
        assert audit_log.call_count == 3

    settings.values[agent_autonomy.SETTING_KEY] = {
        "mode": "full",
        "expires_at": time.time() - 1,
    }
    assert agent_autonomy.current(settings)["mode"] == "normal"

    print(
        "Tool Approval Flow OK - digest, usage unique, refus, expiration et autonomie."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
