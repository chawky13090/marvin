"""Inspection et rollback explicite des événements SSE orphelins archivés."""
from __future__ import annotations
import sqlite3
from typing import Any


def integrity_summary(connection: sqlite3.Connection) -> dict[str, int]:
    orphan_events = int(connection.execute(
        """SELECT COUNT(*) FROM chat_turn_events AS event
           LEFT JOIN chat_turns AS turn ON turn.request_id = event.request_id
           WHERE turn.request_id IS NULL"""
    ).fetchone()[0])
    archived_events = int(connection.execute(
        "SELECT COUNT(*) FROM chat_turn_event_orphan_archive"
    ).fetchone()[0])
    archived_requests = int(connection.execute(
        "SELECT COUNT(DISTINCT request_id) FROM chat_turn_event_orphan_archive"
    ).fetchone()[0])
    return {
        "orphan_events": orphan_events,
        "archived_events": archived_events,
        "archived_requests": archived_requests,
    }


def restore_archived_orphans(
    connection: sqlite3.Connection, *, confirmed: bool
) -> dict[str, Any]:
    """Restaure l'état historique invalide; Marvin doit être arrêté."""
    if confirmed is not True:
        raise ValueError("Confirmation explicite requise.")
    if connection.in_transaction:
        raise RuntimeError("Le rollback exige une connexion hors transaction.")
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        before = int(connection.execute(
            "SELECT COUNT(*) FROM chat_turn_event_orphan_archive"
        ).fetchone()[0])
        connection.execute(
            """INSERT OR IGNORE INTO chat_turn_events
               (request_id, sequence, event_json, created_at)
               SELECT request_id, sequence, event_json, created_at
               FROM chat_turn_event_orphan_archive"""
        )
        restored = int(connection.execute(
            """SELECT COUNT(*) FROM chat_turn_events AS event
               LEFT JOIN chat_turns AS turn ON turn.request_id = event.request_id
               WHERE turn.request_id IS NULL"""
        ).fetchone()[0])
        if restored != before:
            raise RuntimeError("Le rollback des événements archivés est incomplet.")
        connection.commit()
        return {"success": True, "restored_events": restored}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RuntimeError("La clé étrangère SQLite n'a pas été réactivée.")
