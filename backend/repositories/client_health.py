"""Persistance injectable des scores de santé opérationnelle client."""

from __future__ import annotations

import math
import uuid
from contextlib import AbstractContextManager
from typing import Any, Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]
_SCORE_FIELDS = (
    "backup_score",
    "security_score",
    "documentation_score",
    "infrastructure_score",
    "incident_score",
    "global_score",
)


def _bounded_number(
    value: Any,
    *,
    field: str,
    minimum: float = 0.0,
    maximum: float = 100.0,
) -> float:
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(
            f"{field} doit être un nombre fini compris entre "
            f"{minimum:g} et {maximum:g}."
        )
    return number


class ClientHealthRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS client_health_scores (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                backup_score REAL NOT NULL DEFAULT 0,
                security_score REAL NOT NULL DEFAULT 0,
                documentation_score REAL NOT NULL DEFAULT 0,
                infrastructure_score REAL NOT NULL DEFAULT 0,
                incident_score REAL NOT NULL DEFAULT 0,
                global_score REAL NOT NULL DEFAULT 0,
                risk_level TEXT NOT NULL DEFAULT 'medium'
                    CHECK(risk_level IN ('low','medium','high','critical')),
                computed_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS client_health_items (
                id TEXT PRIMARY KEY,
                score_id TEXT NOT NULL,
                client_id TEXT NOT NULL,
                category TEXT NOT NULL,
                label TEXT NOT NULL,
                points REAL NOT NULL DEFAULT 0,
                max_points REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'ok',
                detail TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS client_recommendations (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                score_id TEXT,
                priority TEXT NOT NULL DEFAULT 'medium'
                    CHECK(priority IN ('low','medium','high','critical')),
                category TEXT DEFAULT 'general',
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open'
                    CHECK(status IN ('open','done','dismissed')),
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_health_client "
            "ON client_health_scores(client_id, computed_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_health_items_score "
            "ON client_health_items(score_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_reco_client "
            "ON client_recommendations(client_id, status)"
        )

    @staticmethod
    def _get_score(connection, score_id: str) -> dict | None:
        row = connection.execute(
            "SELECT * FROM client_health_scores WHERE id = ?",
            (score_id,),
        ).fetchone()
        if row is None:
            return None
        result = row_to_dict(row)
        items = connection.execute(
            """SELECT * FROM client_health_items
               WHERE score_id = ?
               ORDER BY created_at ASC, id ASC""",
            (score_id,),
        ).fetchall()
        recommendations = connection.execute(
            """SELECT * FROM client_recommendations
               WHERE score_id = ?
               ORDER BY created_at ASC, id ASC""",
            (score_id,),
        ).fetchall()
        result["items"] = [row_to_dict(item) for item in items]
        result["recommendations"] = [
            row_to_dict(recommendation)
            for recommendation in recommendations
        ]
        return result

    def score_create(
        self,
        data: dict,
        items: list | None = None,
        recommendations: list | None = None,
    ) -> dict:
        client_id = str(data.get("client_id") or "").strip()
        if not client_id:
            raise ValueError("client_id est requis.")
        normalized_scores = {
            field: _bounded_number(
                data.get(field, 0),
                field=field,
            )
            for field in _SCORE_FIELDS
        }
        normalized_items = items if isinstance(items, list) else []
        normalized_recommendations = (
            recommendations if isinstance(recommendations, list) else []
        )
        score_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO client_health_scores (
                       id, client_id, backup_score, security_score,
                       documentation_score, infrastructure_score,
                       incident_score, global_score, risk_level
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    score_id,
                    client_id,
                    *(normalized_scores[field] for field in _SCORE_FIELDS),
                    data.get("risk_level", "medium"),
                ),
            )
            for item in normalized_items:
                if not isinstance(item, dict):
                    raise ValueError(
                        "Chaque élément de santé doit être un objet."
                    )
                max_points = _bounded_number(
                    item.get("max_points", 0),
                    field="max_points",
                    maximum=1_000_000,
                )
                points = _bounded_number(
                    item.get("points", 0),
                    field="points",
                    maximum=max_points,
                )
                connection.execute(
                    """INSERT INTO client_health_items (
                           id, score_id, client_id, category, label,
                           points, max_points, status, detail
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        score_id,
                        client_id,
                        item.get("category", "general"),
                        item.get("label", ""),
                        points,
                        max_points,
                        item.get("status", "ok"),
                        item.get("detail", ""),
                    ),
                )
            for recommendation in normalized_recommendations:
                if not isinstance(recommendation, dict):
                    raise ValueError(
                        "Chaque recommandation doit être un objet."
                    )
                connection.execute(
                    """INSERT INTO client_recommendations (
                           id, client_id, score_id, priority,
                           category, title, description
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        client_id,
                        score_id,
                        recommendation.get("priority", "medium"),
                        recommendation.get("category", "general"),
                        recommendation.get("title", ""),
                        recommendation.get("description", ""),
                    ),
                )
            result = self._get_score(connection, score_id)
        if result is None:
            raise RuntimeError(
                "Le score créé est introuvable avant le commit."
            )
        return result

    def score_get(self, score_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            return self._get_score(connection, score_id)

    def score_latest(self, client_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                """SELECT id FROM client_health_scores
                   WHERE client_id = ?
                   ORDER BY computed_at DESC, id ASC
                   LIMIT 1""",
                (client_id,),
            ).fetchone()
            return self._get_score(connection, row["id"]) if row else None

    def score_history(
        self,
        client_id: str,
        limit: int = 12,
    ) -> list[dict]:
        bounded_limit = min(max(int(limit), 1), 1_000)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                """SELECT * FROM client_health_scores
                   WHERE client_id = ?
                   ORDER BY computed_at DESC, id ASC
                   LIMIT ?""",
                (client_id, bounded_limit),
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def recommendations_list(
        self,
        client_id: str,
        status: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM client_recommendations WHERE client_id = ?"
        params: list[Any] = [client_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC, id ASC"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [row_to_dict(row) for row in rows]


repository = ClientHealthRepository()
health_score_create = repository.score_create
health_score_get = repository.score_get
health_score_latest = repository.score_latest
health_score_history = repository.score_history
health_recommendations_list = repository.recommendations_list
