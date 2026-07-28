"""Persistance injectable des interventions et documents techniques."""

from __future__ import annotations

import json
import uuid
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Callable

from db_connection import db, row_to_dict
from repositories.documentation_templates import DEFAULT_DOCUMENT_TEMPLATES


ConnectionScope = Callable[[], AbstractContextManager]
Clock = Callable[[], datetime]
_JSON_FIELDS = ("asset_ids", "screenshots", "attachments", "tags")
_INTERVENTION_COLUMNS = (
    "title",
    "intervention_type",
    "status",
    "priority",
    "client_id",
    "technician",
    "started_at",
    "resolved_at",
    "duration_minutes",
    "raw_notes",
    "commands_executed",
    "ticket_refs",
    "client_emails",
    "network_config",
    "summary",
    "root_cause",
    "resolution",
    "recommendations",
    "itil_category",
    "rgpd_relevant",
    "number",
)


def _decode_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return decoded if isinstance(decoded, list) else []


def _project_intervention(row: dict | None) -> dict | None:
    if row is None:
        return None
    projected = dict(row)
    for field in _JSON_FIELDS:
        projected[field] = _decode_list(projected.get(field))
    return projected


def _project_document(row: dict | None) -> dict | None:
    if row is None:
        return None
    projected = dict(row)
    projected["tags"] = _decode_list(projected.get("tags"))
    return projected


class DocumentationRepository:
    def __init__(
        self,
        connection_scope: ConnectionScope = db,
        clock: Clock = datetime.now,
    ) -> None:
        self._connection_scope = connection_scope
        self._clock = clock

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS doc_assets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                asset_type TEXT NOT NULL DEFAULT 'workstation'
                    CHECK(asset_type IN (
                        'workstation', 'server', 'firewall', 'switch',
                        'router', 'printer', 'phone', 'nas', 'vm', 'other'
                    )),
                client_id TEXT,
                ip_address TEXT DEFAULT '',
                mac_address TEXT DEFAULT '',
                os TEXT DEFAULT '',
                specs TEXT DEFAULT '',
                location TEXT DEFAULT '',
                criticality TEXT NOT NULL DEFAULT 'medium'
                    CHECK(criticality IN ('low', 'medium', 'high', 'critical')),
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS doc_interventions (
                id TEXT PRIMARY KEY,
                number TEXT NOT NULL,
                title TEXT NOT NULL,
                intervention_type TEXT NOT NULL DEFAULT 'incident'
                    CHECK(intervention_type IN (
                        'incident', 'request', 'change', 'problem',
                        'deployment', 'maintenance', 'audit', 'other'
                    )),
                status TEXT NOT NULL DEFAULT 'open'
                    CHECK(status IN (
                        'open', 'in_progress', 'resolved', 'closed', 'cancelled'
                    )),
                priority TEXT NOT NULL DEFAULT 'medium'
                    CHECK(priority IN ('low', 'medium', 'high', 'critical')),
                client_id TEXT,
                asset_ids TEXT DEFAULT '[]',
                technician TEXT DEFAULT '',
                started_at TEXT,
                resolved_at TEXT,
                duration_minutes INTEGER,
                raw_notes TEXT DEFAULT '',
                commands_executed TEXT DEFAULT '',
                ticket_refs TEXT DEFAULT '',
                client_emails TEXT DEFAULT '',
                network_config TEXT DEFAULT '',
                screenshots TEXT DEFAULT '[]',
                attachments TEXT DEFAULT '[]',
                summary TEXT DEFAULT '',
                root_cause TEXT DEFAULT '',
                resolution TEXT DEFAULT '',
                recommendations TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                itil_category TEXT DEFAULT '',
                rgpd_relevant INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS doc_documents (
                id TEXT PRIMARY KEY,
                intervention_id TEXT,
                client_id TEXT,
                doc_type TEXT NOT NULL
                    CHECK(doc_type IN (
                        'procedure', 'report', 'client_sheet',
                        'recovery_plan', 'maintenance', 'schema',
                        'runbook', 'knowledge_base', 'custom'
                    )),
                format TEXT NOT NULL DEFAULT 'pdf'
                    CHECK(format IN ('pdf', 'docx', 'md', 'html', 'mermaid')),
                title TEXT NOT NULL,
                file_path TEXT,
                content_md TEXT DEFAULT '',
                template_used TEXT DEFAULT '',
                size_bytes INTEGER DEFAULT 0,
                version INTEGER NOT NULL DEFAULT 1,
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS doc_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                description TEXT DEFAULT '',
                content_md TEXT NOT NULL,
                is_builtin INTEGER NOT NULL DEFAULT 0,
                usage_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS doc_sequences (
                kind TEXT NOT NULL,
                year INTEGER NOT NULL,
                value INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (kind, year)
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_interv_client "
            "ON doc_interventions(client_id, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_interv_status "
            "ON doc_interventions(status, priority)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_docs_interv "
            "ON doc_documents(intervention_id, doc_type)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_assets_client "
            "ON doc_assets(client_id, asset_type)"
        )
        count = connection.execute(
            "SELECT COUNT(*) FROM doc_templates"
        ).fetchone()[0]
        if count == 0:
            for doc_type, name, description, content in DEFAULT_DOCUMENT_TEMPLATES:
                connection.execute(
                    """INSERT INTO doc_templates (
                           id, name, doc_type, description,
                           content_md, is_builtin
                       ) VALUES (?, ?, ?, ?, ?, 1)""",
                    (
                        str(uuid.uuid4()),
                        name,
                        doc_type,
                        description,
                        content,
                    ),
                )

    def _next_intervention_number(self, connection) -> str:
        year = self._clock().year
        prefix = f"INT-{year}-"
        highest = connection.execute(
            """SELECT COALESCE(
                   MAX(CAST(substr(number, ?) AS INTEGER)),
                   0
               )
               FROM doc_interventions
               WHERE number LIKE ?""",
            (len(prefix) + 1, f"{prefix}%"),
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO doc_sequences(kind, year, value)
               VALUES ('intervention', ?, ?)
               ON CONFLICT(kind, year) DO UPDATE SET value =
                   CASE
                     WHEN doc_sequences.value < excluded.value
                     THEN excluded.value
                     ELSE doc_sequences.value
                   END""",
            (year, int(highest or 0)),
        )
        sequence = connection.execute(
            """UPDATE doc_sequences
               SET value = value + 1
               WHERE kind = 'intervention' AND year = ?
               RETURNING value""",
            (year,),
        ).fetchone()[0]
        return f"{prefix}{int(sequence):04d}"

    @staticmethod
    def _get_intervention(connection, intervention_id: str) -> dict | None:
        row = connection.execute(
            "SELECT * FROM doc_interventions WHERE id = ?",
            (intervention_id,),
        ).fetchone()
        return _project_intervention(row_to_dict(row))

    def intervention_create(self, data: dict) -> dict:
        intervention_id = str(uuid.uuid4())
        duration = data.get("duration_minutes")
        normalized_duration = int(duration) if duration not in (None, "") else None
        if normalized_duration is not None and normalized_duration < 0:
            raise ValueError("duration_minutes ne peut pas être négatif.")
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            number = data.get("number") or self._next_intervention_number(
                connection
            )
            connection.execute(
                """INSERT INTO doc_interventions (
                       id, number, title, intervention_type, status,
                       priority, client_id, asset_ids, technician,
                       started_at, resolved_at, duration_minutes,
                       raw_notes, commands_executed, ticket_refs,
                       client_emails, network_config, screenshots,
                       attachments, summary, root_cause, resolution,
                       recommendations, tags, itil_category, rgpd_relevant
                   ) VALUES (
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                   )""",
                (
                    intervention_id,
                    number,
                    data.get("title", "Intervention sans titre"),
                    data.get("intervention_type", "incident"),
                    data.get("status", "open"),
                    data.get("priority", "medium"),
                    data.get("client_id"),
                    json.dumps(
                        data.get("asset_ids")
                        if isinstance(data.get("asset_ids"), list)
                        else [],
                        ensure_ascii=False,
                    ),
                    data.get("technician", ""),
                    data.get("started_at"),
                    data.get("resolved_at"),
                    normalized_duration,
                    data.get("raw_notes", ""),
                    data.get("commands_executed", ""),
                    data.get("ticket_refs", ""),
                    data.get("client_emails", ""),
                    data.get("network_config", ""),
                    json.dumps(
                        data.get("screenshots")
                        if isinstance(data.get("screenshots"), list)
                        else [],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        data.get("attachments")
                        if isinstance(data.get("attachments"), list)
                        else [],
                        ensure_ascii=False,
                    ),
                    data.get("summary", ""),
                    data.get("root_cause", ""),
                    data.get("resolution", ""),
                    data.get("recommendations", ""),
                    json.dumps(
                        data.get("tags")
                        if isinstance(data.get("tags"), list)
                        else [],
                        ensure_ascii=False,
                    ),
                    data.get("itil_category", ""),
                    1 if data.get("rgpd_relevant") else 0,
                ),
            )
            result = self._get_intervention(connection, intervention_id)
        if result is None:
            raise RuntimeError("L'intervention créée est introuvable avant commit.")
        return result

    def intervention_get(self, intervention_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            return self._get_intervention(connection, intervention_id)

    def intervention_list(
        self,
        client_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        bounded_limit = min(max(int(limit), 1), 1_000)
        sql = "SELECT * FROM doc_interventions WHERE 1=1"
        params: list[Any] = []
        if client_id:
            sql += " AND client_id = ?"
            params.append(client_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC, id ASC LIMIT ?"
        params.append(bounded_limit)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [
            projected
            for row in rows
            if (
                projected := _project_intervention(row_to_dict(row))
            ) is not None
        ]

    def intervention_update(
        self,
        intervention_id: str,
        data: dict,
    ) -> dict | None:
        columns: list[str] = []
        values: list[Any] = []
        for key in _INTERVENTION_COLUMNS:
            if key not in data:
                continue
            value = data[key]
            if key == "rgpd_relevant":
                value = 1 if value else 0
            if key == "duration_minutes" and value is not None:
                value = int(value)
                if value < 0:
                    raise ValueError(
                        "duration_minutes ne peut pas être négatif."
                    )
            columns.append(f"{key} = ?")
            values.append(value)
        for key in _JSON_FIELDS:
            if key in data:
                value = data[key]
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                columns.append(f"{key} = ?")
                values.append(value)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            if columns:
                columns.append("updated_at = datetime('now')")
                connection.execute(
                    f"UPDATE doc_interventions SET {', '.join(columns)} "
                    "WHERE id = ?",
                    (*values, intervention_id),
                )
            return self._get_intervention(connection, intervention_id)

    def intervention_delete(self, intervention_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "DELETE FROM doc_documents WHERE intervention_id = ?",
                (intervention_id,),
            )
            connection.execute(
                "DELETE FROM doc_interventions WHERE id = ?",
                (intervention_id,),
            )

    def document_create(self, data: dict) -> dict:
        document_id = str(uuid.uuid4())
        size_bytes = int(data.get("size_bytes") or 0)
        version = int(data.get("version") or 1)
        if size_bytes < 0:
            raise ValueError("size_bytes ne peut pas être négatif.")
        if version < 1:
            raise ValueError("version doit être supérieure ou égale à 1.")
        tags = data.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO doc_documents (
                       id, intervention_id, client_id, doc_type, format,
                       title, file_path, content_md, template_used,
                       size_bytes, version, tags
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    document_id,
                    data.get("intervention_id"),
                    data.get("client_id"),
                    data.get("doc_type", "custom"),
                    data.get("format", "pdf"),
                    data.get("title", "Document"),
                    data.get("file_path", ""),
                    data.get("content_md", ""),
                    data.get("template_used", ""),
                    size_bytes,
                    version,
                    json.dumps(tags, ensure_ascii=False),
                ),
            )
            row = connection.execute(
                "SELECT * FROM doc_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        result = _project_document(row_to_dict(row))
        if result is None:
            raise RuntimeError("Le document créé est introuvable avant commit.")
        return result

    def document_list(
        self,
        intervention_id: str | None = None,
        client_id: str | None = None,
        doc_type: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM doc_documents WHERE 1=1"
        params: list[Any] = []
        if intervention_id:
            sql += " AND intervention_id = ?"
            params.append(intervention_id)
        if client_id:
            sql += " AND client_id = ?"
            params.append(client_id)
        if doc_type:
            sql += " AND doc_type = ?"
            params.append(doc_type)
        sql += " ORDER BY created_at DESC, id ASC"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [
            projected
            for row in rows
            if (projected := _project_document(row_to_dict(row))) is not None
        ]

    def document_delete(self, document_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "DELETE FROM doc_documents WHERE id = ?",
                (document_id,),
            )

    def template_list(self, doc_type: str | None = None) -> list[dict]:
        sql = "SELECT * FROM doc_templates"
        params: tuple[Any, ...] = ()
        if doc_type:
            sql += " WHERE doc_type = ?"
            params = (doc_type,)
        sql += " ORDER BY doc_type ASC, usage_count DESC, id ASC"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [row_to_dict(row) for row in rows]

    def template_get(self, template_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM doc_templates WHERE id = ?",
                (template_id,),
            ).fetchone()
        return row_to_dict(row)

    def template_use(self, template_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """UPDATE doc_templates
                   SET usage_count = usage_count + 1
                   WHERE id = ?""",
                (template_id,),
            )

    def asset_create(self, data: dict) -> dict:
        asset_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO doc_assets (
                       id, name, asset_type, client_id, ip_address,
                       mac_address, os, specs, location, criticality, notes
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    asset_id,
                    data.get("name", "Asset"),
                    data.get("asset_type", "workstation"),
                    data.get("client_id"),
                    data.get("ip_address", ""),
                    data.get("mac_address", ""),
                    data.get("os", ""),
                    data.get("specs", ""),
                    data.get("location", ""),
                    data.get("criticality", "medium"),
                    data.get("notes", ""),
                ),
            )
            row = connection.execute(
                "SELECT * FROM doc_assets WHERE id = ?",
                (asset_id,),
            ).fetchone()
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError("L'actif créé est introuvable avant commit.")
        return result

    def asset_list(self, client_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM doc_assets"
        params: tuple[Any, ...] = ()
        if client_id:
            sql += " WHERE client_id = ?"
            params = (client_id,)
        sql += " ORDER BY asset_type ASC, name ASC, id ASC"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [row_to_dict(row) for row in rows]

    def asset_delete(self, asset_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "DELETE FROM doc_assets WHERE id = ?",
                (asset_id,),
            )


repository = DocumentationRepository()
doc_intervention_create = repository.intervention_create
doc_intervention_get = repository.intervention_get
doc_intervention_list = repository.intervention_list
doc_intervention_update = repository.intervention_update
doc_intervention_delete = repository.intervention_delete
doc_document_create = repository.document_create
doc_document_list = repository.document_list
doc_document_delete = repository.document_delete
doc_template_list = repository.template_list
doc_template_get = repository.template_get
doc_template_use = repository.template_use
doc_asset_create = repository.asset_create
doc_asset_list = repository.asset_list
doc_asset_delete = repository.asset_delete
