"""Regressions du journal durable et detachable des tours de chat."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import chat_turn_runtime
import chat_turn_steering
from db_connection import db
from db_migrations import MIGRATIONS, apply_migrations
from repositories.chat_turn_directives import ChatTurnDirectiveRepository
from repositories.tool_approvals import ToolApprovalRepository


def _event(chunk: str) -> dict:
    line = next(line for line in chunk.splitlines() if line.startswith("data: "))
    return json.loads(line[6:])


async def _exercise(path: Path) -> None:
    scope = lambda: db(path)
    release = asyncio.Event()
    starts = 0

    async def producer():
        nonlocal starts
        starts += 1
        yield 'data: {"type":"text","text":"debut"}\n\n'
        await release.wait()
        yield 'data: {"type":"text","text":" fin"}\n\n'
        yield 'data: {"type":"done"}\n\n'

    fingerprint = chat_turn_runtime.payload_hash({"messages": [{"role": "user", "content": "test"}]})
    with patch.object(chat_turn_runtime, "db", scope):
        try:
            chat_turn_runtime._append_event(
                "parent-absent",
                {"type": "done"},
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("Un événement sans tour parent doit être refusé.")
        with db(path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM chat_turn_events WHERE request_id = 'parent-absent'"
            ).fetchone()[0] == 0
            connection.execute(
                """INSERT INTO chat_turns
                   (request_id, payload_hash, conversation_id, status, owner_token)
                   VALUES ('turn-concurrent', 'hash-concurrent', 'conv-1', 'running', ?)""",
                (chat_turn_runtime._PROCESS_TOKEN,),
            )
        sequences = await asyncio.gather(
            *(
                asyncio.to_thread(
                    chat_turn_runtime._append_event,
                    "turn-concurrent",
                    {"type": "text", "text": f"chunk-{index}"},
                )
                for index in range(20)
            )
        )
        assert sorted(sequences) == list(range(1, 21))
        with db(path) as connection:
            assert connection.execute(
                """SELECT COUNT(DISTINCT sequence)
                   FROM chat_turn_events WHERE request_id = 'turn-concurrent'"""
            ).fetchone()[0] == 20

        first_stream = chat_turn_runtime.subscribe(
            request_id="turn-1", fingerprint=fingerprint, conversation_id="conv-1",
            producer_factory=producer,
        )
        first = await anext(first_stream)
        assert _event(first)["text"] == "debut"
        await first_stream.aclose()  # simule un navigateur qui quitte la page
        assert starts == 1

        release.set()
        await asyncio.sleep(0.15)
        replayed = []
        async for chunk in chat_turn_runtime.subscribe(
            request_id="turn-1", fingerprint=fingerprint, conversation_id="conv-1",
            producer_factory=producer, after_sequence=1,
        ):
            replayed.append(_event(chunk))
        assert starts == 1, "Une reconnexion ne doit pas relancer le LLM."
        assert [item["type"] for item in replayed] == ["text", "done"]
        assert [item["turnSeq"] for item in replayed] == [2, 3]

        mismatch = chat_turn_runtime.subscribe(
            request_id="turn-1", fingerprint="autre", conversation_id="conv-1",
            producer_factory=producer,
        )
        try:
            await anext(mismatch)
        except ValueError:
            pass
        else:
            raise AssertionError("Un requestId reutilise avec un payload divergent doit etre refuse.")

        with db(path) as connection:
            connection.execute(
                """INSERT INTO chat_turns
                   (request_id, payload_hash, conversation_id, status, owner_token)
                   VALUES ('turn-old', 'hash-old', 'conv-1', 'running', 'ancien-processus')"""
            )
        assert chat_turn_runtime.recover_orphaned_turns() == 1
        interrupted = []
        async for chunk in chat_turn_runtime.subscribe(
            request_id="turn-old", fingerprint="hash-old", conversation_id="conv-1",
            producer_factory=producer,
        ):
            interrupted.append(_event(chunk))
        assert interrupted[-1]["turnInterrupted"] is True
        assert starts == 1

        with db(path) as connection:
            connection.execute(
                """INSERT INTO chat_turns
                   (request_id, payload_hash, conversation_id, status, owner_token)
                   VALUES ('turn-tool-cut', 'hash-tool', 'conv-1', 'interrupted', 'old')"""
            )
            connection.execute(
                """INSERT INTO chat_turn_events(request_id, sequence, event_json)
                   VALUES ('turn-tool-cut', 1, ?)""",
                (json.dumps({
                    "type": "tool_start",
                    "toolCallId": "tool-cut",
                    "toolName": "file_list",
                }),),
            )
        incomplete = chat_turn_runtime.incomplete_tool_calls("conv-1")
        assert incomplete["tool-cut"]["state"] == "error"
        assert incomplete["tool-cut"]["toolName"] == "file_list"

        async def failing_producer():
            yield 'data: {"type":"text","text":"avant"}\n\n'
            raise RuntimeError("secret-interne C:\\chemin\\prive token=abc")

        with patch.object(chat_turn_runtime.bug_log, "log_bug") as log_bug:
            failed_events = []
            async for chunk in chat_turn_runtime.subscribe(
                request_id="turn-failed",
                fingerprint="hash-failed",
                conversation_id="conv-1",
                producer_factory=failing_producer,
            ):
                failed_events.append(_event(chunk))
        assert [event["type"] for event in failed_events] == ["text", "error"]
        failure = failed_events[-1]
        assert len(failure["incident"]) == 32
        assert failure["incident"] in failure["message"]
        assert "secret-interne" not in str(failed_events)
        log_bug.assert_called_once()
        logged = log_bug.call_args
        assert logged.args[:2] == (
            "chat_turn_producer_failure",
            "Le producteur SSE d'un tour a échoué.",
        )
        assert logged.kwargs["context"]["error_type"] == "RuntimeError"
        assert "secret-interne" not in str(logged)
        with db(path) as connection:
            row = connection.execute(
                "SELECT status,error FROM chat_turns WHERE request_id='turn-failed'"
            ).fetchone()
        assert row["status"] == "failed"
        assert "secret-interne" not in row["error"]

        with patch.object(
            chat_turn_runtime.bug_log,
            "log_bug",
            side_effect=OSError("journal indisponible"),
        ):
            degraded_events = []
            async for chunk in chat_turn_runtime.subscribe(
                request_id="turn-failed-log",
                fingerprint="hash-failed-log",
                conversation_id="conv-1",
                producer_factory=failing_producer,
            ):
                degraded_events.append(_event(chunk))
        assert [event["type"] for event in degraded_events] == ["text", "error"]
        with db(path) as connection:
            degraded_row = connection.execute(
                "SELECT status,error FROM chat_turns WHERE request_id='turn-failed-log'"
            ).fetchone()
        assert degraded_row["status"] == "failed"
        assert "secret-interne" not in degraded_row["error"]

        try:
            chat_turn_runtime._finish("turn-1", "running")
        except ValueError:
            pass
        else:
            raise AssertionError("Un statut non terminal devait être refusé.")

        # Une attente d'approbation conserve l'exclusion mutuelle. La continuation
        # partage la même racine puis libère le slot; une tâche « ensuite » est
        # journalisée avant ``done`` afin que le frontend puisse l'enchaîner.
        steering_repository = ChatTurnDirectiveRepository(scope)
        with patch.object(chat_turn_steering, "repository", steering_repository), patch.object(
            chat_turn_steering, "connection_scope", scope
        ), patch.object(chat_turn_steering, "enabled", return_value=True):
            chat_turn_steering.reserve("conv-steering", "root-steering", "conv-steering")
            chat_turn_steering.create(
                "root-steering",
                "79c9226a-8080-4558-a3a9-44d347eddf68",
                "next",
                "Puis vérifie le résultat.",
            )
            chat_turn_steering.checkpoint("root-steering", phase="before_model_iteration")
            with db(path) as connection:
                for request_id in ("approval-part", "continuation-part"):
                    connection.execute(
                        """INSERT INTO chat_turns
                           (request_id, payload_hash, conversation_id, status, owner_token)
                           VALUES (?, ?, 'conv-steering', 'running', ?)""",
                        (request_id, f"hash-{request_id}", chat_turn_runtime._PROCESS_TOKEN),
                    )
                connection.execute(
                    """INSERT INTO tool_approval_requests (
                           id, call_digest, tool_name, arguments_json,
                           conversation_id, request_id, source, risk_tier,
                           status, expires_at
                       ) VALUES (?, ?, ?, '{}', ?, ?, ?, ?, 'pending', ?)""",
                    (
                        "approval-live",
                        "digest-live",
                        "file_delete",
                        "conv-steering",
                        "root-steering",
                        "tool_gateway",
                        4,
                        time.time() + 300,
                    ),
                )

            async def approval_producer():
                yield 'data: {"type":"done","stopReason":"pending_confirmation"}\n\n'

            await chat_turn_runtime._produce(
                "approval-part",
                approval_producer(),
                steering_root_request_id="root-steering",
                conversation_key="conv-steering",
            )
            assert chat_turn_steering.active("conv-steering")["root_request_id"] == "root-steering"

            async def continuation_producer():
                yield 'data: {"type":"done","stopReason":"criteria_satisfied"}\n\n'

            await chat_turn_runtime._produce(
                "continuation-part",
                continuation_producer(),
                steering_root_request_id="root-steering",
                conversation_key="conv-steering",
            )
            assert chat_turn_steering.active("conv-steering") is None
            with db(path) as connection:
                rows = connection.execute(
                    "SELECT event_json FROM chat_turn_events WHERE request_id = 'continuation-part' ORDER BY sequence"
                ).fetchall()
            types = [json.loads(row[0])["type"] for row in rows]
            assert types == ["directive_ready", "done"]

            # Un simple stopReason sans approbation persistée ne doit jamais
            # immobiliser la conversation ni bloquer l'arrêt de Marvin.
            chat_turn_steering.reserve("conv-no-approval", "root-no-approval", "conv-no-approval")
            with db(path) as connection:
                connection.execute(
                    """INSERT INTO chat_turns
                       (request_id, payload_hash, conversation_id, status, owner_token)
                       VALUES ('part-no-approval', 'hash-no-approval',
                               'conv-no-approval', 'running', ?)""",
                    (chat_turn_runtime._PROCESS_TOKEN,),
                )
            await chat_turn_runtime._produce(
                "part-no-approval",
                approval_producer(),
                steering_root_request_id="root-no-approval",
                conversation_key="conv-no-approval",
            )
            assert chat_turn_steering.active("conv-no-approval") is None

            # Une seconde demande concurrente devient un reçu terminal explicite,
            # pas un tour fantôme ``running`` ni une seconde exécution métier.
            chat_turn_steering.reserve("conv-busy", "root-busy", "conv-busy")
            busy_started = False

            async def busy_producer():
                nonlocal busy_started
                busy_started = True
                yield 'data: {"type":"done"}\n\n'

            busy_events = []
            async for chunk in chat_turn_runtime.subscribe(
                request_id="turn-busy",
                fingerprint="hash-busy",
                conversation_id="conv-busy",
                conversation_key="conv-busy",
                root_request_id="root-other",
                producer_factory=busy_producer,
            ):
                busy_events.append(_event(chunk))
            assert busy_started is False
            assert busy_events[-1]["code"] == "conversation_busy"
            with db(path) as connection:
                assert connection.execute(
                    "SELECT status FROM chat_turns WHERE request_id = 'turn-busy'"
                ).fetchone()[0] == "failed"

            # Le démarrage nettoie aussi un ancien slot sans approbation vivante.
            with db(path) as connection:
                connection.execute(
                    """INSERT INTO chat_turns
                       (request_id, payload_hash, conversation_id, status, owner_token)
                       VALUES ('root-stale', 'hash-stale', 'conv-stale', 'completed', 'old')"""
                )
                connection.execute(
                    """INSERT INTO chat_turn_slots
                       (conversation_key, root_request_id, conversation_id)
                       VALUES ('conv-stale', 'root-stale', 'conv-stale')"""
                )
            assert chat_turn_runtime.recover_orphaned_turns() == 0
            assert chat_turn_steering.active("conv-stale") is None


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="marvin-chat-turn-") as directory:
        path = Path(directory) / "turns.db"
        with db(path) as connection:
            apply_migrations(connection, MIGRATIONS)
            ToolApprovalRepository.ensure_schema(connection)
        # Les scénarios historiques du journal durable ne fournissent pas de clé
        # de conversation. Ils caractérisent ce composant seul; le scénario de
        # pilotage réactive explicitement la fonctionnalité dans son propre bloc.
        with patch.object(chat_turn_steering, "enabled", return_value=False):
            asyncio.run(_exercise(path))
        with db(path) as connection:
            assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            assert connection.execute(
                "SELECT status FROM chat_turns WHERE request_id = 'turn-1'"
            ).fetchone()[0] == "completed"
    print("Chat Turn Runtime OK - detach, replay, curseur et interruption sure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
