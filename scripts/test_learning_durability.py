"""Contrats de persistance et de rappel de l'apprentissage durable."""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import learning
from repositories.learned_knowledge import LearnedKnowledgeRepository


def _scope(path: Path):
    @contextmanager
    def connect():
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    return connect


class FakeClient:
    def __init__(self, fact, qa) -> None:
        self.fact = fact
        self.qa = qa
        self.deleted = []

    def query_points(self, *, collection_name, **_kwargs):
        record = self.fact if collection_name == "learned_facts" else self.qa
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    id=record["id"],
                    score=0.99,
                    payload={"fingerprint": record["fingerprint"]},
                ),
                SimpleNamespace(
                    id="orphan",
                    score=1.0,
                    payload={"fingerprint": "0" * 64},
                ),
            ]
        )

    def delete(self, *, collection_name, points_selector):
        self.deleted.append((collection_name, points_selector))


async def exercise(path: Path) -> None:
    repository = LearnedKnowledgeRepository(_scope(path))
    fact, created = repository.upsert(
        "fact",
        "L'utilisateur préfère les réponses courtes.",
        source="test",
    )
    assert created is True
    duplicate, created = repository.upsert(
        "fact",
        "L'utilisateur préfère les réponses courtes.",
        source="other",
    )
    assert created is False and duplicate["id"] == fact["id"]
    qa, created = repository.upsert(
        "qa",
        "Comment vérifier un service ?",
        "Consulter son état et ses journaux.",
        source="test",
    )
    assert created is True
    assert repository.counts() == {"facts": 1, "qa": 1}

    client = FakeClient(fact, qa)
    original_repository = learning.repository
    original_migrated = learning._LEGACY_MIGRATED
    learning.repository = repository
    learning._LEGACY_MIGRATED = True
    try:
        with (
            patch.object(learning.vs, "get_client", return_value=client),
            patch.object(learning.vs, "embed", AsyncMock(return_value=[0.1] * 768)),
        ):
            recalled = await learning.recall(
                "réponses courtes et service",
                min_fact=0.4,
                min_qa=0.4,
            )
            assert recalled["facts"] == [fact["question"]]
            assert recalled["qa"] == [(qa["question"], qa["answer"])]
            assert "orphan" not in str(recalled)
            assert learning.delete_learned("facts", fact["id"]) is True
            assert client.deleted == [("learned_facts", [fact["id"]])]
        assert repository.counts() == {"facts": 0, "qa": 1}
    finally:
        learning.repository = original_repository
        learning._LEGACY_MIGRATED = original_migrated

    try:
        repository.upsert("fact", "x" * 4_001, source="test")
    except ValueError:
        pass
    else:
        raise AssertionError("Un fait hors limite devait être refusé.")


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        asyncio.run(exercise(Path(directory) / "learning.db"))
    print("Learning Durability OK - autorité SQLite, provenance et rappel filtré.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
