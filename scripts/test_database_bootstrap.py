"""Contrat du composition root SQLite déterministe et injectable."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from database_bootstrap import initialize_database


class FakeConnection:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def commit(self) -> None:
        self.events.append("commit")


class FakeRepository:
    def __init__(self, name: str, events: list[str], *, fail: bool = False) -> None:
        self.name = name
        self.events = events
        self.fail = fail

    def ensure_schema(self, connection: FakeConnection) -> None:
        assert connection.events is self.events
        self.events.append(f"repository:{self.name}")
        if self.fail:
            raise RuntimeError("schema-failure")


def _factory(events: list[str]):
    @contextmanager
    def factory() -> Iterator[FakeConnection]:
        events.append("open")
        try:
            yield FakeConnection(events)
            events.append("context-commit")
        except BaseException:
            events.append("context-rollback")
            raise
        finally:
            events.append("close")

    return factory


def _check_order() -> None:
    events: list[str] = []
    repositories = (
        FakeRepository("a", events),
        FakeRepository("b", events),
    )

    def legacy(connection: FakeConnection) -> int:
        connection.events.append("legacy")
        return 0

    def schema(connection: FakeConnection) -> list[int]:
        connection.events.append("migrations")
        return []

    initialize_database(
        connection_factory=_factory(events),
        repositories=repositories,
        migrate_legacy=legacy,
        migrate_schema=schema,
    )
    assert events == [
        "open",
        "repository:a",
        "repository:b",
        "legacy",
        "commit",
        "migrations",
        "context-commit",
        "close",
    ]


def _check_failure_and_validation() -> None:
    events: list[str] = []
    repositories = (
        FakeRepository("ok", events),
        FakeRepository("broken", events, fail=True),
    )
    try:
        initialize_database(
            connection_factory=_factory(events),
            repositories=repositories,
            migrate_legacy=lambda _: 0,
            migrate_schema=lambda _: [],
        )
    except RuntimeError as exc:
        assert str(exc) == "schema-failure"
    else:
        raise AssertionError("Une panne de repository devait interrompre le bootstrap.")
    assert events == [
        "open",
        "repository:ok",
        "repository:broken",
        "context-rollback",
        "close",
    ]

    duplicate = FakeRepository("duplicate", [])
    try:
        initialize_database(repositories=(duplicate, duplicate))
    except ValueError:
        pass
    else:
        raise AssertionError("Un repository dupliqué devait être refusé.")

    try:
        initialize_database(repositories=(object(),))
    except TypeError:
        pass
    else:
        raise AssertionError("Un repository sans ensure_schema devait être refusé.")


def main() -> int:
    _check_order()
    _check_failure_and_validation()
    print("Database Bootstrap OK - ordre, injection, panne, rollback et doublons.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
