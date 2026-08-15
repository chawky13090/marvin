from __future__ import annotations

import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import chat_turn_steering as steering
from repositories.chat_turn_directives import ChatTurnDirectiveRepository, ConversationBusyError


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "steering.db"

        @contextmanager
        def scope():
            connection = sqlite3.connect(path, timeout=5)
            connection.row_factory = sqlite3.Row
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

        repository = ChatTurnDirectiveRepository(scope)
        with patch.object(steering, "repository", repository), patch.object(
            steering, "connection_scope", scope
        ), patch.object(
            steering.tool_approvals, "invalidate_pending_for_request", return_value=1
        ) as invalidate:
            steering.reserve("conversation-a", "root-a", "conversation-a")
            try:
                steering.reserve("conversation-a", "root-b", "conversation-a")
            except ConversationBusyError:
                pass
            else:
                raise AssertionError("Deux racines ne doivent jamais partager une conversation.")
            directive, created = steering.create(
                "root-a", "9a18526f-0f21-4554-a650-497ffe2179bb", "append", "Privilégie les fichiers récents."
            )
            assert created is True and directive["status"] == "received"
            invalidate.assert_called_once_with("root-a", reason="directive_payload_changed")
            applied, stopped = steering.checkpoint("root-a", phase="before_model_iteration")
            assert stopped is False
            assert applied[0]["status"] == "applied"
            queued, _ = steering.create(
                "root-a", "62aa8914-a85a-4429-89bd-9a85bb72ac5e", "next", "Puis résume le résultat."
            )
            assert queued["status"] == "received"
            applied, stopped = steering.checkpoint("root-a", phase="before_model_iteration")
            assert stopped is False and applied == []
            deferred = steering.list_public("root-a")[-1]
            assert deferred["status"] == "deferred"
            assert deferred["waitingFor"] == {"kind": "root_turn_terminal"}
            ready = steering.terminal("root-a")
            assert len(ready) == 1 and ready[0]["status"] == "applied"
            stop, _ = steering.create(
                "root-a", "0749d04e-c82f-44a1-bd05-dad69ee1ad3f", "stop", ""
            )
            assert stop["kind"] == "stop"
            applied, stopped = steering.checkpoint("root-a", phase="before_model_iteration")
            assert stopped is True and applied[0]["kind"] == "stop"
            assert steering.release("root-a") is True
    print("Chat Turn Steering Runtime OK - exclusion, approval, file suivante, checkpoint et stop")


if __name__ == "__main__":
    main()
