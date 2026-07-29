"""Composition déterministe du schéma et des migrations SQLite de Marvin."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from typing import ContextManager, Protocol

from db_connection import db
from db_migrations import apply_migrations
from oauth_legacy_migration import migrate_legacy_tokens
from repositories.billing import repository as billing_repository
from repositories.client_health import repository as client_health_repository
from repositories.command_safety import repository as command_safety_repository
from repositories.cron_jobs import repository as cron_job_repository
from repositories.documentation import repository as documentation_repository
from repositories.events import repository as event_repository
from repositories.executions import repository as execution_repository
from repositories.flashcards import repository as flashcard_repository
from repositories.it_knowledge import repository as it_knowledge_repository
from repositories.learned_knowledge import repository as learned_knowledge_repository
from repositories.memories import repository as memory_repository
from repositories.network_inventory import repository as network_inventory_repository
from repositories.operations import repository as operations_repository
from repositories.system_snapshots import repository as system_snapshot_repository
from repositories.tool_templates import repository as tool_template_repository


class SchemaRepository(Protocol):
    def ensure_schema(self, connection: sqlite3.Connection) -> None: ...


ConnectionFactory = Callable[[], ContextManager[sqlite3.Connection]]
LegacyMigration = Callable[[sqlite3.Connection], int]
SchemaMigration = Callable[[sqlite3.Connection], list[int]]

SCHEMA_REPOSITORIES: tuple[SchemaRepository, ...] = (
    execution_repository,
    system_snapshot_repository,
    tool_template_repository,
    cron_job_repository,
    network_inventory_repository,
    billing_repository,
    documentation_repository,
    operations_repository,
    command_safety_repository,
    client_health_repository,
    it_knowledge_repository,
    learned_knowledge_repository,
    memory_repository,
    flashcard_repository,
    event_repository,
)


def initialize_database(
    *,
    connection_factory: ConnectionFactory = db,
    repositories: Iterable[SchemaRepository] = SCHEMA_REPOSITORIES,
    migrate_legacy: LegacyMigration = migrate_legacy_tokens,
    migrate_schema: SchemaMigration = apply_migrations,
) -> None:
    """Initialise une fois, dans un ordre stable, derrière des dépendances injectables."""
    ordered = tuple(repositories)
    identities = tuple(id(repository) for repository in ordered)
    if len(identities) != len(set(identities)):
        raise ValueError("Un repository de schéma ne peut pas être exécuté deux fois.")
    if any(not callable(getattr(repository, "ensure_schema", None)) for repository in ordered):
        raise TypeError("Repository de schéma invalide.")

    with connection_factory() as connection:
        for repository in ordered:
            repository.ensure_schema(connection)
        # DPAPI est externe à SQLite : la relecture doit être acquise avant la
        # migration SQL, sans prétendre former une transaction distribuée.
        migrate_legacy(connection)
        connection.commit()
        migrate_schema(connection)
