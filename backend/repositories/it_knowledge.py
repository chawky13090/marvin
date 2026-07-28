"""Persistance injectable et bornée de la base de connaissances IT."""

from __future__ import annotations

import math
import uuid
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlsplit

from db_connection import db, row_to_dict
from repositories.it_knowledge_catalog import IT_KNOWLEDGE_CATALOG


ConnectionScope = Callable[[], AbstractContextManager]
Clock = Callable[[], datetime]
IdFactory = Callable[[], Any]

PRICING_MODELS = frozenset(
    {"opensource", "free", "freemium", "paid", "saas", "unknown"}
)
MAX_ID_LENGTH = 160
MAX_NAME_LENGTH = 300
MAX_CATEGORY_LENGTH = 200
MAX_SHORT_TEXT_LENGTH = 1_000
MAX_LONG_TEXT_LENGTH = 8_000
MAX_URL_LENGTH = 2_048
MAX_QUERY_LENGTH = 1_000
MAX_LIST_LIMIT = 500
MAX_SEARCH_LIMIT = 100

_FIELD_LIMITS = {
    "category": MAX_CATEGORY_LENGTH,
    "vendor": MAX_SHORT_TEXT_LENGTH,
    "description": MAX_LONG_TEXT_LENGTH,
    "use_cases": MAX_LONG_TEXT_LENGTH,
    "pros": MAX_LONG_TEXT_LENGTH,
    "cons": MAX_LONG_TEXT_LENGTH,
    "typical_price": MAX_SHORT_TEXT_LENGTH,
    "platforms": MAX_SHORT_TEXT_LENGTH,
    "alternatives": MAX_LONG_TEXT_LENGTH,
    "tags": MAX_SHORT_TEXT_LENGTH,
    "best_for": MAX_LONG_TEXT_LENGTH,
    "source": MAX_SHORT_TEXT_LENGTH,
}
_UPDATABLE_FIELDS = (
    "category",
    "vendor",
    "description",
    "use_cases",
    "pros",
    "cons",
    "pricing_model",
    "typical_price",
    "platforms",
    "alternatives",
    "official_url",
    "tags",
    "rating",
    "best_for",
    "source",
)


def _required_text(value: Any, *, field: str, limit: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} est requis.")
    if len(normalized) > limit:
        raise ValueError(f"{field} dépasse la limite de {limit} caractères.")
    return normalized


def _optional_text(value: Any, *, field: str, limit: int) -> str:
    normalized = str(value or "").strip()
    if len(normalized) > limit:
        raise ValueError(f"{field} dépasse la limite de {limit} caractères.")
    return normalized


def _bounded_limit(value: Any, *, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError("limit doit être un entier.")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit doit être un entier.") from exc
    if normalized < 1 or normalized > maximum:
        raise ValueError(f"limit doit être compris entre 1 et {maximum}.")
    return normalized


def _rating(value: Any) -> float:
    try:
        normalized = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("rating doit être un nombre entre 0 et 5.") from exc
    if not math.isfinite(normalized) or not 0 <= normalized <= 5:
        raise ValueError("rating doit être un nombre fini entre 0 et 5.")
    return normalized


def _official_url(value: Any) -> str:
    normalized = _optional_text(
        value,
        field="official_url",
        limit=MAX_URL_LENGTH,
    )
    if not normalized:
        return ""
    parsed = urlsplit(normalized)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("official_url contient un port invalide.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
    ):
        raise ValueError(
            "official_url doit être une URL HTTP(S) sans identifiants "
            "et sur un port standard."
        )
    return normalized


class ItKnowledgeRepository:
    def __init__(
        self,
        connection_scope: ConnectionScope = db,
        clock: Clock = datetime.now,
        id_factory: IdFactory = uuid.uuid4,
    ) -> None:
        self._connection_scope = connection_scope
        self._clock = clock
        self._id_factory = id_factory

    def ensure_schema(self, connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS it_knowledge (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                vendor TEXT DEFAULT '',
                description TEXT DEFAULT '',
                use_cases TEXT DEFAULT '',
                pros TEXT DEFAULT '',
                cons TEXT DEFAULT '',
                pricing_model TEXT DEFAULT 'paid'
                    CHECK(pricing_model IN (
                        'opensource','free','freemium','paid','saas','unknown'
                    )),
                typical_price TEXT DEFAULT '',
                platforms TEXT DEFAULT '',
                alternatives TEXT DEFAULT '',
                official_url TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                rating REAL DEFAULT 0,
                best_for TEXT DEFAULT '',
                source TEXT DEFAULT 'curated',
                times_used INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_itkb_cat "
            "ON it_knowledge(category, name)"
        )
        if (
            connection.execute(
                "SELECT COUNT(*) FROM it_knowledge"
            ).fetchone()[0]
            == 0
        ):
            self._seed(connection)

    def _seed(self, connection) -> None:
        for item in IT_KNOWLEDGE_CATALOG:
            name, category, vendor, description, use_cases, pricing, price, platforms, best_for, tags = item
            connection.execute(
                """INSERT INTO it_knowledge (
                       id, name, category, vendor, description, use_cases,
                       pricing_model, typical_price, platforms, best_for,
                       tags, source
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'curated')""",
                (
                    str(self._id_factory()),
                    name,
                    category,
                    vendor,
                    description,
                    use_cases,
                    pricing,
                    price,
                    platforms,
                    best_for,
                    tags,
                ),
            )

    def list(
        self,
        category: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        normalized_limit = _bounded_limit(limit, maximum=MAX_LIST_LIMIT)
        normalized_category = None
        if category is not None and str(category).strip():
            normalized_category = _required_text(
                category,
                field="category",
                limit=MAX_CATEGORY_LENGTH,
            )
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            if normalized_category:
                rows = connection.execute(
                    """SELECT * FROM it_knowledge
                       WHERE category = ?
                       ORDER BY name, id LIMIT ?""",
                    (normalized_category, normalized_limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM it_knowledge
                       ORDER BY category, name, id LIMIT ?""",
                    (normalized_limit,),
                ).fetchall()
        return [row_to_dict(row) for row in rows]

    def categories(self) -> list[str]:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                """SELECT DISTINCT category FROM it_knowledge
                   ORDER BY category"""
            ).fetchall()
        return [row[0] for row in rows]

    def search(self, query: str, limit: int = 12) -> list[dict]:
        normalized_query = _required_text(
            query,
            field="query",
            limit=MAX_QUERY_LENGTH,
        ).lower()
        normalized_limit = _bounded_limit(limit, maximum=MAX_SEARCH_LIMIT)
        pattern = f"%{normalized_query}%"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                """SELECT * FROM it_knowledge
                   WHERE lower(name) LIKE ?
                      OR lower(category) LIKE ?
                      OR lower(use_cases) LIKE ?
                      OR lower(tags) LIKE ?
                      OR lower(best_for) LIKE ?
                      OR lower(description) LIKE ?
                      OR lower(vendor) LIKE ?
                   ORDER BY times_used DESC, name, id LIMIT ?""",
                (
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    normalized_limit,
                ),
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def get(self, name_or_id: str) -> dict | None:
        normalized = _required_text(
            name_or_id,
            field="name_or_id",
            limit=MAX_NAME_LENGTH,
        )
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                """SELECT * FROM it_knowledge
                   WHERE id = ? OR lower(name) = ?""",
                (normalized, normalized.lower()),
            ).fetchone()
        return row_to_dict(row) if row else None

    def upsert(self, data: dict) -> dict:
        if not isinstance(data, dict):
            raise ValueError("data doit être un objet.")
        name = _required_text(
            data.get("name"),
            field="name",
            limit=MAX_NAME_LENGTH,
        )
        normalized: dict[str, Any] = {}
        for field, limit in _FIELD_LIMITS.items():
            if field in data and data[field] not in (None, ""):
                normalized[field] = _optional_text(
                    data[field],
                    field=field,
                    limit=limit,
                )
        if "pricing_model" in data and data["pricing_model"] not in (None, ""):
            pricing = str(data["pricing_model"]).strip().lower()
            if pricing not in PRICING_MODELS:
                raise ValueError("pricing_model est invalide.")
            normalized["pricing_model"] = pricing
        if "official_url" in data and data["official_url"] not in (None, ""):
            normalized["official_url"] = _official_url(data["official_url"])
        if "rating" in data and data["rating"] not in (None, ""):
            normalized["rating"] = _rating(data["rating"])
        now = self._clock().strftime("%Y-%m-%d %H:%M:%S")

        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            existing = connection.execute(
                "SELECT id FROM it_knowledge WHERE lower(name) = ?",
                (name.lower(),),
            ).fetchone()
            if existing:
                knowledge_id = existing[0]
                selected = [
                    field
                    for field in _UPDATABLE_FIELDS
                    if field in normalized
                ]
                if selected:
                    assignments = ", ".join(f"{field} = ?" for field in selected)
                    connection.execute(
                        f"""UPDATE it_knowledge
                            SET {assignments}, updated_at = ?
                            WHERE id = ?""",
                        (
                            *[normalized[field] for field in selected],
                            now,
                            knowledge_id,
                        ),
                    )
            else:
                knowledge_id = str(self._id_factory())
                connection.execute(
                    """INSERT INTO it_knowledge (
                           id, name, category, vendor, description, use_cases,
                           pros, cons, pricing_model, typical_price, platforms,
                           alternatives, official_url, tags, rating, best_for,
                           source, created_at, updated_at
                       ) VALUES (
                           ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?
                       )""",
                    (
                        knowledge_id,
                        name,
                        normalized.get("category", "Autre"),
                        normalized.get("vendor", ""),
                        normalized.get("description", ""),
                        normalized.get("use_cases", ""),
                        normalized.get("pros", ""),
                        normalized.get("cons", ""),
                        normalized.get("pricing_model", "unknown"),
                        normalized.get("typical_price", ""),
                        normalized.get("platforms", ""),
                        normalized.get("alternatives", ""),
                        normalized.get("official_url", ""),
                        normalized.get("tags", ""),
                        normalized.get("rating", 0),
                        normalized.get("best_for", ""),
                        normalized.get("source", "learned"),
                        now,
                        now,
                    ),
                )
            row = connection.execute(
                "SELECT * FROM it_knowledge WHERE id = ?",
                (knowledge_id,),
            ).fetchone()
        result = row_to_dict(row)
        if not result:
            raise RuntimeError(
                "L'entrée IT est introuvable après son enregistrement."
            )
        return result

    def increment_usage(self, name_or_id: str) -> None:
        normalized = _required_text(
            name_or_id,
            field="name_or_id",
            limit=MAX_NAME_LENGTH,
        )
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """UPDATE it_knowledge
                   SET times_used = times_used + 1
                   WHERE id = ? OR lower(name) = ?""",
                (normalized, normalized.lower()),
            )


repository = ItKnowledgeRepository()
it_kb_list = repository.list
it_kb_categories = repository.categories
it_kb_search = repository.search
it_kb_get = repository.get
it_kb_upsert = repository.upsert
it_kb_increment_usage = repository.increment_usage
