"""Régressions SQLite du repository de connaissances IT."""

from __future__ import annotations

import math
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db_connection import db
from repositories.it_knowledge import ItKnowledgeRepository
from repositories.it_knowledge_catalog import IT_KNOWLEDGE_CATALOG


NOW = datetime(2026, 7, 28, 15, 0, 0)


def _must_reject(operation) -> None:
    try:
        operation()
    except ValueError:
        return
    raise AssertionError("Une entrée invalide a été acceptée.")


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "it-knowledge.db"
        repository = ItKnowledgeRepository(
            connection_scope=lambda: db(path),
            clock=lambda: NOW,
        )
        with db(path) as connection:
            repository.ensure_schema(connection)
            repository.ensure_schema(connection)
            seed_count = connection.execute(
                "SELECT COUNT(*) FROM it_knowledge"
            ).fetchone()[0]
        assert seed_count == len(IT_KNOWLEDGE_CATALOG) == 34
        assert repository.get("Nmap")["name"] == "Nmap"
        assert repository.get(repository.get("Nmap")["id"])["name"] == "Nmap"
        assert repository.get("absent") is None
        assert repository.categories() == sorted(repository.categories())
        assert repository.list("Diagnostic", 2)[0]["name"] == (
            "Advanced IP Scanner"
        )
        assert any(
            entry["name"] == "RustDesk"
            for entry in repository.search("souverain", 20)
        )

        repository._id_factory = lambda: "learned-entry"
        created = repository.upsert(
            {
                "name": "Produit test",
                "category": "Diagnostic",
                "vendor": "Éditeur",
                "description": "Description",
                "pricing_model": "free",
                "official_url": "https://example.com/product",
                "rating": 4.5,
            }
        )
        assert created["id"] == "learned-entry"
        assert created["created_at"] == "2026-07-28 15:00:00"
        assert created["updated_at"] == "2026-07-28 15:00:00"
        assert created["rating"] == 4.5

        updated = repository.upsert(
            {
                "name": "Produit test",
                "description": "Nouvelle description",
                "rating": 5,
                "vendor": "",
            }
        )
        assert updated["id"] == "learned-entry"
        assert updated["description"] == "Nouvelle description"
        assert updated["vendor"] == "Éditeur"
        assert updated["rating"] == 5
        repository.increment_usage("Produit test")
        repository.increment_usage("learned-entry")
        assert repository.get("Produit test")["times_used"] == 2

        invalid_operations = (
            lambda: repository.list(None, 0),
            lambda: repository.list(None, 501),
            lambda: repository.list(None, True),
            lambda: repository.search("", 1),
            lambda: repository.search("x", 101),
            lambda: repository.get(""),
            lambda: repository.increment_usage(""),
            lambda: repository.upsert([]),
            lambda: repository.upsert({"name": ""}),
            lambda: repository.upsert({"name": "N" * 301}),
            lambda: repository.upsert(
                {"name": "Invalide", "pricing_model": "gratuit"}
            ),
            lambda: repository.upsert(
                {"name": "Invalide", "rating": math.inf}
            ),
            lambda: repository.upsert(
                {"name": "Invalide", "rating": 5.1}
            ),
            lambda: repository.upsert(
                {
                    "name": "Invalide",
                    "official_url": "file:///etc/passwd",
                }
            ),
            lambda: repository.upsert(
                {
                    "name": "Invalide",
                    "official_url": "https://user:secret@example.com",
                }
            ),
            lambda: repository.upsert(
                {
                    "name": "Invalide",
                    "official_url": "https://example.com:8443",
                }
            ),
        )
        for operation in invalid_operations:
            _must_reject(operation)
        assert repository.list("", 1) == repository.list(None, 1)

        existing_id = repository.get("Nmap")["id"]
        repository._id_factory = lambda: existing_id
        before = len(repository.list(None, 500))
        try:
            repository.upsert(
                {"name": "Collision", "category": "Diagnostic"}
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("La collision d'identifiant doit échouer.")
        assert len(repository.list(None, 500)) == before
        assert repository.get("Collision") is None

    import database
    from repositories import it_knowledge

    names = (
        "it_kb_list",
        "it_kb_categories",
        "it_kb_search",
        "it_kb_get",
        "it_kb_upsert",
        "it_kb_increment_usage",
    )
    for name in names:
        assert getattr(database, name) is getattr(it_knowledge, name), name

    print(
        "IT Knowledge Repository OK - catalogue 34, recherches bornées, "
        "validation, usage, collision, rollback et 6 façades."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
