"""Connexion SQLite partagee et frontiere transactionnelle de Marvin."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from config import DB_PATH


def get_conn(path: str | Path = DB_PATH) -> sqlite3.Connection:
    """Ouvre une connexion configuree de facon identique pour tout le backend."""
    connection = sqlite3.connect(str(path), check_same_thread=False, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        connection.close()
        raise sqlite3.OperationalError(
            "SQLite n'a pas activé l'intégrité référentielle."
        )
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA secure_delete=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA cell_size_check=ON")
    return connection


@contextmanager
def db(path: str | Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Commit atomique en succes, rollback integral en cas d'exception."""
    connection = get_conn(path)
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def row_to_dict(row: sqlite3.Row | dict | None) -> dict | None:
    if row is None:
        return None
    return dict(row)
