"""Regressions du repository conversations/messages et des transactions SQLite."""

from __future__ import annotations

import ast
import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

from db_connection import db, get_conn
from db_migrations import MIGRATIONS, apply_migrations
from repositories.conversations import ConversationRepository
from rollback_conversation_archiving import rollback_database


EXPORTED = {
    "create_conversation",
    "create_message",
    "delete_conversation",
    "get_conversation",
    "get_messages_by_conversation",
    "get_recent_user_messages",
    "list_conversations",
    "search_conversations",
    "set_conversation_archived",
    "set_conversation_pinned",
    "update_conversation_project",
    "update_conversation_title",
    "upgrade_conversation_title_silent",
}


def _check_database_facade() -> None:
    tree = ast.parse((BACKEND / "database.py").read_text(encoding="utf-8-sig"))
    imported: set[str] = set()
    definitions: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "repositories.conversations":
            imported.update(alias.asname or alias.name for alias in node.names)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions.add(node.name)
    assert imported == EXPORTED
    assert not EXPORTED.intersection(definitions)


def _check_repository(path: Path) -> None:
    with db(path) as connection:
        apply_migrations(connection, MIGRATIONS)
    repository = ConversationRepository(lambda: db(path))

    first = repository.create_conversation("Premiere")
    second = repository.create_conversation("Seconde")
    repository.set_conversation_pinned(first["id"], True)
    assert repository.list_conversations()[0]["id"] == first["id"]
    archived = repository.set_conversation_archived(second["id"], True)
    assert archived and archived["archived_at"]
    assert {item["id"] for item in repository.list_conversations()} == {first["id"]}
    assert {item["id"] for item in repository.list_conversations(archived=True)} == {
        second["id"]
    }
    restored = repository.set_conversation_archived(second["id"], False)
    assert restored and restored["archived_at"] is None

    message = repository.create_message(
        first["id"],
        "user",
        "Contenu unique pour recherche et repetition",
        tool_calls=[{"name": "demo"}],
        tool_results=[{"success": True}],
    )
    assert message["tool_calls"] == [{"name": "demo"}]
    assert message["tool_results"] == [{"success": True}]
    first_request = repository.create_message(
        first["id"], "user", "Message idempotent", client_request_id="request-unique-1",
    )
    repeated_request = repository.create_message(
        first["id"], "user", "Message idempotent", client_request_id="request-unique-1",
    )
    assert repeated_request["id"] == first_request["id"]
    try:
        repository.create_message(
            first["id"], "user", "Contenu divergent", client_request_id="request-unique-1",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Un request id reutilise avec un autre contenu devait etre refuse.")
    repository.create_message(
        second["id"], "user", "Contenu unique pour recherche et repetition"
    )
    assert {item["id"] for item in repository.search_conversations("unique")} == {
        first["id"],
        second["id"],
    }
    assert repository.get_recent_user_messages() == [
        "Contenu unique pour recherche et repetition",
        "Message idempotent",
    ]

    with db(path) as connection:
        connection.execute(
            "UPDATE conversations SET updated_at = '2001-01-01 00:00:00' WHERE id = ?",
            (first["id"],),
        )
    repository.upgrade_conversation_title_silent(first["id"], "Titre soigne")
    updated = repository.get_conversation(first["id"])
    assert updated and updated["title"] == "Titre soigne"
    assert updated["updated_at"] == "2001-01-01 00:00:00"

    try:
        repository.create_message(first["id"], "role-invalide", "refuse")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("Le CHECK SQL des roles devait refuser la valeur.")
    assert len(repository.get_messages_by_conversation(first["id"])) == 2

    repository.delete_conversation(first["id"])
    assert repository.get_conversation(first["id"]) is None
    with db(path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM messages WHERE conversation_id = ?", (first["id"],)
        ).fetchone()[0] == 0

    backup = rollback_database(path)
    assert backup.is_file()
    with db(path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(conversations)").fetchall()
        }
        assert "archived_at" not in columns
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def _check_transaction_rollback(path: Path) -> None:
    try:
        with db(path) as connection:
            connection.execute(
                "INSERT INTO settings (key, value) VALUES ('rollback-test', 'present')"
            )
            raise RuntimeError("annulation volontaire")
    except RuntimeError:
        pass
    with db(path) as connection:
        assert connection.execute(
            "SELECT value FROM settings WHERE key = 'rollback-test'"
        ).fetchone() is None
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 10000


def main() -> int:
    _check_database_facade()
    with tempfile.TemporaryDirectory(prefix="marvin-repository-") as directory:
        path = Path(directory) / "repository.db"
        _check_repository(path)
        _check_transaction_rollback(path)
        connection = get_conn(path)
        try:
            assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            connection.close()
    print("Conversation Repository OK - facade, CRUD, recherche, cascade et rollback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
