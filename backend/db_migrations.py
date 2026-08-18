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
    Migration(
        version=3,
        name="chat-turn-and-action-receipts",
        statements=(
            "ALTER TABLE messages ADD COLUMN client_request_id TEXT",
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_client_request
               ON messages(conversation_id, client_request_id)
               WHERE client_request_id IS NOT NULL""",
            """CREATE TABLE IF NOT EXISTS action_receipts (
                idempotency_key TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                args_hash TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK(status IN ('started', 'completed', 'unknown')),
                owner_token TEXT NOT NULL,
                result_json TEXT,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT
            )""",
            "CREATE INDEX IF NOT EXISTS idx_action_receipts_request ON action_receipts(request_id, started_at)",
            "CREATE INDEX IF NOT EXISTS idx_action_receipts_status ON action_receipts(status, started_at)",
        ),
    ),
    Migration(
        version=4,
        name="durable-chat-turn-streams",
        statements=(
            """CREATE TABLE IF NOT EXISTS chat_turns (
                request_id TEXT PRIMARY KEY,
                payload_hash TEXT NOT NULL,
                conversation_id TEXT,
                status TEXT NOT NULL
                    CHECK(status IN ('running', 'completed', 'failed', 'interrupted')),
                owner_token TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS chat_turn_events (
                request_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (request_id, sequence),
                FOREIGN KEY (request_id) REFERENCES chat_turns(request_id) ON DELETE CASCADE
            )""",
            "CREATE INDEX IF NOT EXISTS idx_chat_turns_status ON chat_turns(status, updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_chat_turn_events_request ON chat_turn_events(request_id, sequence)",
        ),
    ),
    Migration(
        version=5,
        name="archive-orphaned-chat-turn-events",
        statements=(
            """CREATE TABLE IF NOT EXISTS chat_turn_event_orphan_archive (
                request_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                archived_at TEXT NOT NULL DEFAULT (datetime('now')),
                reason TEXT NOT NULL
                    CHECK(reason = 'missing-chat-turn-parent'),
                PRIMARY KEY (request_id, sequence)
            )""",
            """INSERT OR IGNORE INTO chat_turn_event_orphan_archive
               (request_id, sequence, event_json, created_at, reason)
               SELECT event.request_id, event.sequence, event.event_json,
                      event.created_at, 'missing-chat-turn-parent'
               FROM chat_turn_events AS event
               LEFT JOIN chat_turns AS turn
                 ON turn.request_id = event.request_id
               WHERE turn.request_id IS NULL""",
            """DELETE FROM chat_turn_events
               WHERE EXISTS (
                   SELECT 1 FROM chat_turn_event_orphan_archive AS archive
                   WHERE archive.request_id = chat_turn_events.request_id
                     AND archive.sequence = chat_turn_events.sequence
                     AND archive.reason = 'missing-chat-turn-parent'
               )
               AND NOT EXISTS (
                   SELECT 1 FROM chat_turns
                   WHERE chat_turns.request_id = chat_turn_events.request_id
               )""",
        ),
    ),
    Migration(
        version=6,
        name="oauth-token-tombstone",
        statements=(
            """CREATE TABLE IF NOT EXISTS oauth_token_migration_metadata (
                provider TEXT PRIMARY KEY,
                token_type TEXT,
                scope TEXT,
                expires_at TEXT,
                migrated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""",
            """CREATE TABLE oauth_tokens_safe (
                provider TEXT PRIMARY KEY
                    CHECK(provider IN ('google','microsoft')),
                token_type TEXT,
                scope TEXT,
                expires_at TEXT,
                migrated_at TEXT NOT NULL
            )""",
            """INSERT INTO oauth_tokens_safe
               (provider,token_type,scope,expires_at,migrated_at)
               SELECT provider,token_type,scope,expires_at,migrated_at
               FROM oauth_token_migration_metadata""",
            "DROP TABLE oauth_tokens",
            "ALTER TABLE oauth_tokens_safe RENAME TO oauth_tokens",
            "DROP TABLE oauth_token_migration_metadata",
        ),
    ),
    Migration(
        version=7,
        name="chat-turn-steering-directives",
        statements=(
            """CREATE TABLE IF NOT EXISTS chat_turn_slots (
                conversation_key TEXT PRIMARY KEY,
                root_request_id TEXT NOT NULL UNIQUE,
                conversation_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""",
            """CREATE TABLE IF NOT EXISTS chat_turn_directives (
                id TEXT PRIMARY KEY,
                client_directive_id TEXT NOT NULL,
                root_request_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('append','redirect','next','stop')),
                directive_text TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'received'
                    CHECK(status IN ('received','deferred','applied','rejected','cancelled')),
                waiting_for_json TEXT,
                reason_code TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                applied_at TEXT,
                UNIQUE(root_request_id, client_directive_id),
                UNIQUE(root_request_id, sequence)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_chat_turn_directives_status
               ON chat_turn_directives(root_request_id, status, sequence)""",
        ),
    ),
    Migration(
        version=8,
        name="portable-infrastructure-asset-registry",
        statements=(
            """CREATE TABLE IF NOT EXISTS network_devices (
                id TEXT PRIMARY KEY,
                ip TEXT NOT NULL,
                mac TEXT DEFAULT '',
                hostname TEXT DEFAULT '',
                custom_name TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(mac, ip)
            )""",
            """CREATE TABLE network_devices_v8 (
                id TEXT PRIMARY KEY,
                ip TEXT NOT NULL,
                mac TEXT DEFAULT '',
                hostname TEXT DEFAULT '',
                custom_name TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                asset_type TEXT NOT NULL DEFAULT 'unknown',
                vendor TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                os_family TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT '',
                site TEXT NOT NULL DEFAULT '',
                management_protocols TEXT NOT NULL DEFAULT '[]',
                tags TEXT NOT NULL DEFAULT '[]',
                ssh_connection_id TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
                source TEXT NOT NULL DEFAULT 'discovery',
                updated_at TEXT NOT NULL DEFAULT '',
                UNIQUE(mac, ip)
            )""",
            """INSERT INTO network_devices_v8
               (id,ip,mac,hostname,custom_name,notes,first_seen,last_seen)
               SELECT id,ip,mac,hostname,custom_name,notes,first_seen,last_seen
               FROM network_devices""",
            "DROP TABLE network_devices",
            "ALTER TABLE network_devices_v8 RENAME TO network_devices",
            "CREATE INDEX IF NOT EXISTS idx_network_devices_last_seen ON network_devices(last_seen DESC)",
            "CREATE INDEX IF NOT EXISTS idx_network_devices_asset_type ON network_devices(asset_type, enabled)",
            "CREATE INDEX IF NOT EXISTS idx_network_devices_site ON network_devices(site, enabled)",
        ),
    ),
    Migration(
        version=9,
        name="snmpv3-profiles-and-asset-link",
        statements=(
            """CREATE TABLE snmp_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                username TEXT NOT NULL,
                auth_protocol TEXT NOT NULL CHECK(auth_protocol IN ('sha1','sha256')),
                priv_protocol TEXT NOT NULL CHECK(priv_protocol IN ('none','aes128')),
                context_name TEXT NOT NULL DEFAULT '',
                port INTEGER NOT NULL DEFAULT 161 CHECK(port BETWEEN 1 AND 65535),
                secret_ref TEXT NOT NULL,
                last_test_ok INTEGER,
                last_test_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""",
            """CREATE TABLE network_devices_v9 (
                id TEXT PRIMARY KEY, ip TEXT NOT NULL, mac TEXT DEFAULT '', hostname TEXT DEFAULT '',
                custom_name TEXT DEFAULT '', notes TEXT DEFAULT '',
                first_seen TEXT NOT NULL DEFAULT (datetime('now')), last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                asset_type TEXT NOT NULL DEFAULT 'unknown', vendor TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
                os_family TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '', site TEXT NOT NULL DEFAULT '',
                management_protocols TEXT NOT NULL DEFAULT '[]', tags TEXT NOT NULL DEFAULT '[]',
                ssh_connection_id TEXT NOT NULL DEFAULT '', snmp_profile_id TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)), source TEXT NOT NULL DEFAULT 'discovery',
                updated_at TEXT NOT NULL DEFAULT '', UNIQUE(mac, ip)
            )""",
            """INSERT INTO network_devices_v9
               (id,ip,mac,hostname,custom_name,notes,first_seen,last_seen,asset_type,vendor,model,os_family,role,site,
                management_protocols,tags,ssh_connection_id,snmp_profile_id,enabled,source,updated_at)
               SELECT id,ip,mac,hostname,custom_name,notes,first_seen,last_seen,asset_type,vendor,model,os_family,role,site,
                       management_protocols,tags,ssh_connection_id,snmp_profile_id,enabled,source,updated_at
               FROM network_devices""",
            "DROP TABLE network_devices",
            "ALTER TABLE network_devices_v9 RENAME TO network_devices",
            "CREATE INDEX idx_network_devices_last_seen ON network_devices(last_seen DESC)",
            "CREATE INDEX idx_network_devices_asset_type ON network_devices(asset_type, enabled)",
            "CREATE INDEX idx_network_devices_site ON network_devices(site, enabled)",
            "CREATE INDEX idx_network_devices_snmp_profile ON network_devices(snmp_profile_id)",
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
            # Précondition historique de v9, préparée dans le même savepoint
            # sans réécrire le checksum de la migration déjà appliquée.
            if migration.version == 9:
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(network_devices)")
                }
                if "snmp_profile_id" not in columns:
                    connection.execute(
                        "ALTER TABLE network_devices ADD COLUMN snmp_profile_id TEXT NOT NULL DEFAULT ''"
                    )
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
