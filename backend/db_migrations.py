"""Migrations SQLite versionnees, transactionnelles et verifiables de Marvin."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Iterable


MIGRATIONS_TABLE = "schema_migrations"


class MigrationError(RuntimeError):
    """Erreur de contrat ou d'application du schema."""


class MigrationDriftError(MigrationError):
    """Le contenu d'une migration deja appliquee a change."""


class SchemaAheadError(MigrationError):
    """La base a ete ouverte par une version de Marvin plus recente."""


class MigrationApplyError(MigrationError):
    """Une migration n'a pas pu etre appliquee et a ete annulee."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.version <= 0:
            raise ValueError("La version d'une migration doit etre strictement positive.")
        if not self.name.strip():
            raise ValueError("Le nom d'une migration ne peut pas etre vide.")
        if not self.statements or any(not statement.strip() for statement in self.statements):
            raise ValueError("Une migration doit contenir des instructions SQL non vides.")

    @property
    def checksum(self) -> str:
        payload = "\0".join(
            (str(self.version), self.name, *self.statements)
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="legacy-schema-baseline",
        statements=("SELECT 1",),
    ),
    Migration(
        version=2,
        name="python-owned-core-schema",
        statements=(
            """CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                instructions TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""",
            """CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'Nouvelle conversation',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                project_id TEXT,
                pinned INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
            )""",
            """CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
                content TEXT NOT NULL,
                tool_calls TEXT,
                tool_results TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )""",
            """CREATE TABLE IF NOT EXISTS oauth_tokens (
                provider TEXT PRIMARY KEY CHECK(provider IN ('google', 'microsoft')),
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                token_type TEXT DEFAULT 'Bearer',
                scope TEXT,
                expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""",
            """CREATE TABLE IF NOT EXISTS file_actions_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                source_path TEXT NOT NULL,
                destination_path TEXT,
                details TEXT,
                status TEXT NOT NULL DEFAULT 'completed'
                    CHECK(status IN ('completed', 'failed', 'reverted')),
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""",
            """CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""",
            """CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL
                    CHECK(category IN ('user_profile', 'preference', 'fact', 'habit')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""",
            """CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'in_progress', 'done', 'cancelled')),
                priority TEXT NOT NULL DEFAULT 'medium'
                    CHECK(priority IN ('low', 'medium', 'high', 'urgent')),
                due_date TEXT,
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""",
            """CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                tags TEXT DEFAULT '[]',
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""",
            """CREATE TABLE IF NOT EXISTS email_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                variables TEXT DEFAULT '[]',
                category TEXT DEFAULT 'general',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""",
            """CREATE TABLE IF NOT EXISTS automation_rules (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_config TEXT DEFAULT '{}',
                action_type TEXT NOT NULL,
                action_config TEXT DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""",
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_file_actions_created ON file_actions_log(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority, status)",
            "CREATE INDEX IF NOT EXISTS idx_notes_pinned ON notes(pinned DESC, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC)",
        ),
    ),
)


def _validate_catalog(migrations: tuple[Migration, ...]) -> None:
    versions = [migration.version for migration in migrations]
    if versions != sorted(versions) or len(versions) != len(set(versions)):
        raise MigrationError(
            "Le catalogue des migrations doit etre strictement ordonne et sans doublon."
        )


def _ensure_history_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def applied_migrations(connection: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    _ensure_history_table(connection)
    rows = connection.execute(
        f"SELECT version, name, checksum FROM {MIGRATIONS_TABLE} ORDER BY version"
    ).fetchall()
    return {int(row[0]): (str(row[1]), str(row[2])) for row in rows}


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: Iterable[Migration] = MIGRATIONS,
) -> list[int]:
    """Applique les migrations absentes et retourne leurs versions.

    Chaque migration utilise un SAVEPOINT SQLite : une instruction invalide annule
    uniquement la migration courante, sans laisser de table ou de colonne partielle.
    Le checksum interdit de modifier silencieusement une migration deja livree.
    """

    catalog = tuple(migrations)
    _validate_catalog(catalog)
    history = applied_migrations(connection)
    declared = {migration.version: migration for migration in catalog}
    unknown = sorted(set(history) - set(declared))
    if unknown:
        raise SchemaAheadError(
            "La base contient des migrations inconnues de ce code : "
            + ", ".join(map(str, unknown))
        )

    for version, (stored_name, stored_checksum) in history.items():
        migration = declared[version]
        if stored_name != migration.name or stored_checksum != migration.checksum:
            raise MigrationDriftError(
                f"Derive detectee pour la migration {version} ({stored_name})."
            )

    applied: list[int] = []
    for migration in catalog:
        if migration.version in history:
            continue
        savepoint = f"marvin_migration_{migration.version}"
        connection.execute(f"SAVEPOINT {savepoint}")
        try:
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                f"INSERT INTO {MIGRATIONS_TABLE} (version, name, checksum) VALUES (?, ?, ?)",
                (migration.version, migration.name, migration.checksum),
            )
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception as exc:
            connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise MigrationApplyError(
                f"Echec de la migration {migration.version} ({migration.name}); rollback effectue."
            ) from exc
        applied.append(migration.version)
    return applied


def current_schema_version(connection: sqlite3.Connection) -> int:
    history = applied_migrations(connection)
    return max(history, default=0)
