"""Regressions deterministes du moteur de migrations SQLite."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db_migrations import (
    MIGRATIONS,
    Migration,
    MigrationApplyError,
    MigrationDriftError,
    MigrationError,
    SchemaAheadError,
    apply_migrations,
    current_schema_version,
)


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _check_apply_once() -> None:
    connection = _connection()
    catalog = (
        Migration(1, "create-example", ("CREATE TABLE example (id INTEGER PRIMARY KEY)",)),
        Migration(2, "add-value", ("ALTER TABLE example ADD COLUMN value TEXT",)),
    )
    assert apply_migrations(connection, catalog) == [1, 2]
    assert apply_migrations(connection, catalog) == []
    assert current_schema_version(connection) == 2
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    assert [row[1] for row in connection.execute("PRAGMA table_info(example)")] == [
        "id",
        "value",
    ]
    connection.close()


def _check_failed_migration_rolls_back() -> None:
    connection = _connection()
    broken = (
        Migration(
            1,
            "broken",
            ("CREATE TABLE partial_table (id INTEGER)", "SQL VOLONTAIREMENT INVALIDE"),
        ),
    )
    try:
        apply_migrations(connection, broken)
    except MigrationApplyError as exc:
        assert "rollback effectue" in str(exc)
    else:
        raise AssertionError("Une migration SQL invalide devait echouer.")
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='partial_table'"
    ).fetchone() is None
    assert current_schema_version(connection) == 0
    connection.close()


def _check_drift_and_schema_ahead() -> None:
    connection = _connection()
    initial = (Migration(1, "stable", ("CREATE TABLE stable (id INTEGER)",)),)
    apply_migrations(connection, initial)
    try:
        apply_migrations(connection, (Migration(1, "changed", ("SELECT 1",)),))
    except MigrationDriftError:
        pass
    else:
        raise AssertionError("La derive d'une migration appliquee devait etre refusee.")
    try:
        apply_migrations(connection, ())
    except SchemaAheadError:
        pass
    else:
        raise AssertionError("Un schema plus recent que le code devait etre refuse.")
    connection.close()


def _check_catalog_order() -> None:
    connection = _connection()
    try:
        apply_migrations(
            connection,
            (Migration(2, "second", ("SELECT 2",)), Migration(1, "first", ("SELECT 1",))),
        )
    except MigrationError:
        pass
    else:
        raise AssertionError("Un catalogue non ordonne devait etre refuse.")
    connection.close()


def _check_fresh_marvin_schema() -> None:
    connection = _connection()
    assert apply_migrations(connection, MIGRATIONS) == [1, 2, 3]
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    expected = {
        "projects",
        "conversations",
        "messages",
        "oauth_tokens",
        "file_actions_log",
        "settings",
        "memories",
        "tasks",
        "notes",
        "email_templates",
        "automation_rules",
        "action_receipts",
        "schema_migrations",
    }
    assert expected <= tables, expected - tables
    conversation_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(conversations)")
    }
    assert {"project_id", "pinned"} <= conversation_columns
    message_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(messages)")
    }
    assert "client_request_id" in message_columns
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    connection.close()


def main() -> int:
    _check_apply_once()
    _check_failed_migration_rolls_back()
    _check_drift_and_schema_ahead()
    _check_catalog_order()
    _check_fresh_marvin_schema()
    print("Migrations SQLite OK - idempotence, checksum, rollback et compatibilite.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
