"""Offline tests for the unconnected chat steering repository."""

from __future__ import annotations

import sqlite3
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from repositories.chat_turn_directives import (
    ChatTurnDirectiveRepository,
    ConversationBusyError,
    DirectiveConflictError,
    DirectiveLimitError,
    InvalidDirectiveTransition,
    MAX_DIRECTIVES_PER_TURN,
)


def _repository():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row

    @contextmanager
    def scope():
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    return ChatTurnDirectiveRepository(scope), connection


def _id() -> str:
    return str(uuid.uuid4())


def main() -> None:
    repo, connection = _repository()
    provisional = _id()
    root = "request-root-1"
    slot = repo.reserve_slot(conversation_key=provisional, root_request_id=root)
    assert slot["root_request_id"] == root
    assert repo.reserve_slot(conversation_key=provisional, root_request_id=root)["root_request_id"] == root

    try:
        repo.reserve_slot(conversation_key=provisional, root_request_id="request-root-2")
    except ConversationBusyError:
        pass
    else:
        raise AssertionError("Un deuxième tour de la même conversation devait être refusé.")
    other = repo.reserve_slot(conversation_key=_id(), root_request_id="request-root-2")
    assert other["root_request_id"] == "request-root-2"

    client_id = _id()
    first, created = repo.create_directive(
        root_request_id=root,
        client_directive_id=client_id,
        kind="append",
        text="Prends aussi en compte les journaux Windows.",
    )
    assert created is True and first["sequence"] == 1 and first["status"] == "received"
    duplicate, created = repo.create_directive(
        root_request_id=root,
        client_directive_id=client_id,
        kind="append",
        text="Prends aussi en compte les journaux Windows.",
    )
    assert created is False and duplicate["id"] == first["id"]
    try:
        repo.create_directive(
            root_request_id=root,
            client_directive_id=client_id,
            kind="redirect",
            text="Autre contenu",
        )
    except DirectiveConflictError:
        pass
    else:
        raise AssertionError("Un idempotency key réutilisé avec un autre contenu devait échouer.")

    redirect1, _ = repo.create_directive(
        root_request_id=root, client_directive_id=_id(), kind="redirect", text="Direction A"
    )
    redirect2, _ = repo.create_directive(
        root_request_id=root, client_directive_id=_id(), kind="redirect", text="Direction B"
    )
    by_id = {row["id"]: row for row in repo.list_for_turn(root)}
    assert by_id[redirect1["id"]]["status"] == "cancelled"
    assert by_id[redirect2["id"]]["sequence"] == 3

    deferred = repo.transition(
        first["id"],
        expected_status="received",
        target_status="deferred",
        waiting_for={"kind": "tool_call", "tool_name": "winget_upgrade", "tool_call_id": "call-1", "cancellable": False},
    )
    assert deferred["status"] == "deferred" and "winget_upgrade" in deferred["waiting_for_json"]
    applied = repo.transition(
        first["id"], expected_status="deferred", target_status="applied"
    )
    assert applied["status"] == "applied" and applied["applied_at"]
    for operation in (
        lambda: repo.cancel(first["id"]),
        lambda: repo.transition(first["id"], expected_status="applied", target_status="cancelled"),
    ):
        try:
            operation()
        except InvalidDirectiveTransition:
            pass
        else:
            raise AssertionError("Une directive terminale devait rester immuable.")

    stop, _ = repo.create_directive(
        root_request_id=root, client_directive_id=_id(), kind="stop"
    )
    assert stop["sequence"] == 4
    try:
        repo.create_directive(
            root_request_id=root, client_directive_id=_id(), kind="append", text="Trop tard"
        )
    except DirectiveConflictError:
        pass
    else:
        raise AssertionError("Une précision après stop devait être refusée.")

    try:
        repo.create_directive(
            root_request_id="foreign-root", client_directive_id=_id(), kind="append", text="x"
        )
    except DirectiveConflictError:
        pass
    else:
        raise AssertionError("Une directive sans slot racine devait être refusée.")

    long_text = "x" * 8001
    try:
        repo.create_directive(
            root_request_id="request-root-2", client_directive_id=_id(), kind="append", text=long_text
        )
    except DirectiveLimitError:
        pass
    else:
        raise AssertionError("Une directive trop longue devait être refusée.")

    limit_root = "request-limit"
    repo.reserve_slot(conversation_key=_id(), root_request_id=limit_root)
    for index in range(MAX_DIRECTIVES_PER_TURN):
        row, _ = repo.create_directive(
            root_request_id=limit_root,
            client_directive_id=_id(),
            kind="append",
            text=f"directive-{index}",
        )
        repo.transition(row["id"], expected_status="received", target_status="applied")
    try:
        repo.create_directive(
            root_request_id=limit_root, client_directive_id=_id(), kind="append", text="overflow"
        )
    except DirectiveLimitError:
        pass
    else:
        raise AssertionError("La 33e directive devait être refusée.")

    collision_key = "conversation-final"
    repo.reserve_slot(conversation_key=collision_key, root_request_id="request-collision")
    try:
        repo.rebind_slot(
            provisional_key=provisional,
            conversation_key=collision_key,
            conversation_id="conversation-final",
            root_request_id=root,
        )
    except ConversationBusyError:
        pass
    else:
        raise AssertionError("Un rattachement vers un slot occupé devait échouer.")
    assert repo.release_slot(conversation_key=collision_key, root_request_id="request-collision") is True
    rebound = repo.rebind_slot(
        provisional_key=provisional,
        conversation_key=collision_key,
        conversation_id="conversation-final",
        root_request_id=root,
    )
    assert rebound["conversation_id"] == "conversation-final"
    assert repo.release_slot(conversation_key=collision_key, root_request_id="wrong-root") is False
    assert repo.release_slot(conversation_key=collision_key, root_request_id=root) is True

    connection.close()
    print("Chat Turn Directives Repository OK - slots, idempotence, ordering, bounds and transitions")


if __name__ == "__main__":
    main()
