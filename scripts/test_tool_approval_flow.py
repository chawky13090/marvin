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
        continuation = repository.claim_continuation(
            first["id"],
            conversation_id="conversation-1",
            request_id="continuation-1",
        )
        assert continuation and continuation["decision_reason"] == "continued:continuation-1"
        continuation_replay = repository.claim_continuation(
            first["id"],
            conversation_id="conversation-1",
            request_id="continuation-1",
        )
        assert continuation_replay and continuation_replay["id"] == first["id"]
        assert repository.claim_continuation(
            first["id"],
            conversation_id="conversation-1",
            request_id="continuation-2",
        ) is None
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

        stale = repository.create_or_reuse(
            call_digest="c" * 64,
            tool_name="pc_run_powershell",
            arguments={"script": "Get-Service Tailscale"},
            conversation_id="conversation-2",
            request_id="request-3",
            source="chat",
            risk_tier=4,
        )
        current = repository.create_or_reuse(
            call_digest="d" * 64,
            tool_name="pc_app_launch",
            arguments={"app_name": "Tailscale"},
            conversation_id="conversation-2",
            request_id="request-4",
            source="chat",
            risk_tier=2,
        )
        stale_status = repository.resolve_status(stale["id"])
        assert stale_status and stale_status["status"] == "expired"
        assert stale_status["decision_reason"] == "superseded"
        assert stale_status["arguments"] == {}
        assert repository.resolve_status(current["id"])["status"] == "pending"
        assert repository.claim(stale["id"])["claimed"] is False

        independent = repository.create_or_reuse(
            call_digest="e" * 64,
            tool_name="file_delete",
            arguments={"path": "C:/temp/other.txt"},
            conversation_id="conversation-3",
            request_id="request-5",
            source="chat",
            risk_tier=5,
        )
        assert repository.resolve_status(current["id"])["status"] == "pending"
        assert repository.resolve_status(independent["id"])["status"] == "pending"

        direct_old = repository.create_or_reuse(
            call_digest="f" * 64,
            tool_name="pc_run_command",
            arguments={"command": "whoami"},
            conversation_id="conversation-4",
            request_id="request-6",
            source="chat",
            risk_tier=4,
        )
        direct_new = repository.create_or_reuse(
            call_digest="1" * 64,
            tool_name="pc_app_launch",
            arguments={"app_name": "notepad"},
            conversation_id="conversation-4",
            request_id="request-7",
            source="chat",
            risk_tier=2,
        )
        # Simule une carte héritée créée avant l'introduction de l'obsolescence.
        with scope() as connection:
            connection.execute(
                """UPDATE tool_approval_requests
                   SET status = 'pending', decision_reason = '',
                       arguments_json = '{"command":"whoami"}'
                   WHERE id = ?""",
                (direct_old["id"],),
            )
        direct_claim = repository.claim(direct_old["id"])
        assert direct_claim and direct_claim["status"] == "expired"
        assert direct_claim["decision_reason"] == "superseded"
        repository.deny(direct_new["id"])
        assert repository.resolve_status(direct_new["id"])["status"] == "denied"

    settings = Settings()
    with patch.object(agent_autonomy.audit, "log_action") as audit_log:
        assert agent_autonomy.current(settings)["mode"] == "normal"
        auto = agent_autonomy.configure(settings, "auto", 60)
        assert auto["active"] and auto["mode"] == "auto"
        assert agent_autonomy.allows("auto", 3)
        assert not agent_autonomy.allows("auto", 4)
        full = agent_autonomy.configure(settings, "full", 60)
        assert full["active"] and agent_autonomy.allows("full", 5)
        assert full["expires_at"] is None
        assert full["persistence"] == "until_revoked"
        assert settings.values[agent_autonomy.SETTING_KEY]["expires_at"] is None
        normal = agent_autonomy.configure(settings, "normal", 60)
        assert not normal["active"]
        assert normal["persistence"] == "revoked"
        assert audit_log.call_count == 3

    settings.values[agent_autonomy.SETTING_KEY] = {
        "mode": "full",
        "expires_at": time.time() - 1,
    }
    legacy_full = agent_autonomy.current(settings)
    assert legacy_full["mode"] == "full"
    assert legacy_full["active"] is True
    assert legacy_full["persistence"] == "until_revoked"

    print(
        "Tool Approval Flow OK - usage unique, refus, expiration, remplacement et autonomie."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
