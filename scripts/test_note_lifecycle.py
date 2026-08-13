"""Défaillances injectées SQLite/Qdrant du cycle de vie des notes."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import note_lifecycle
import vector_store
from api import notes as notes_api
from fastapi import HTTPException


NOTE = {
    "id": "note-1",
    "title": "Runbook",
    "content": "Contenu fixture",
    "tags": ["ops"],
    "pinned": False,
    "created_at": "2026-08-13 10:00:00",
    "updated_at": "2026-08-13 10:00:00",
}


async def _run() -> None:
    with patch.object(
        vector_store,
        "upsert_document",
        AsyncMock(return_value=True),
    ) as upsert:
        assert await vector_store.index_note(
            "note-1",
            "Runbook",
            "Contenu fixture",
            ["ops"],
        ) is True
    indexed_text = "Runbook\nContenu fixture"
    indexed_metadata = upsert.await_args.args[3]
    assert indexed_metadata["content_sha256"] == __import__("hashlib").sha256(
        indexed_text.encode("utf-8")
    ).hexdigest()

    with (
        patch.object(note_lifecycle.db, "create_note", return_value=NOTE),
        patch.object(note_lifecycle, "_index", AsyncMock()),
    ):
        created = await note_lifecycle.create("Runbook", "Contenu fixture", ["ops"])
    assert created["success"] is True
    assert created["consistency"] == "complete"

    with (
        patch.object(note_lifecycle.db, "create_note", return_value=NOTE),
        patch.object(
            note_lifecycle,
            "_index",
            AsyncMock(side_effect=RuntimeError("fixture_qdrant_down")),
        ),
    ):
        degraded = await note_lifecycle.create("Runbook", "Contenu fixture", ["ops"])
    assert degraded["success"] is True
    assert degraded["consistency"] == "degraded"
    assert degraded["warnings"] == ["qdrant_index:RuntimeError"]
    assert "Contenu fixture" not in str(degraded["warnings"])

    updated_note = {**NOTE, "title": "Runbook v2"}
    with (
        patch.object(note_lifecycle.db, "update_note", return_value=updated_note),
        patch.object(
            note_lifecycle,
            "_index",
            AsyncMock(side_effect=RuntimeError("fixture_qdrant_down")),
        ),
    ):
        updated = await note_lifecycle.update("note-1", {"title": "Runbook v2"})
    assert updated["success"] is True and updated["consistency"] == "degraded"

    with (
        patch.object(note_lifecycle.db, "get_note", return_value=NOTE),
        patch.object(
            note_lifecycle,
            "_delete_index",
            AsyncMock(side_effect=RuntimeError("fixture_qdrant_down")),
        ),
        patch.object(note_lifecycle.db, "delete_note") as delete_source,
    ):
        refused = await note_lifecycle.delete("note-1")
    assert refused == {
        "success": False,
        "deleted": False,
        "stage": "qdrant",
        "error_type": "RuntimeError",
        "compensated": True,
    }
    delete_source.assert_not_called()

    with (
        patch.object(note_lifecycle.db, "get_note", return_value=NOTE),
        patch.object(note_lifecycle, "_delete_index", AsyncMock()),
        patch.object(
            note_lifecycle.db,
            "delete_note",
            side_effect=OSError("fixture_sqlite_down"),
        ),
        patch.object(note_lifecycle.db, "restore_note", return_value=NOTE) as restore,
        patch.object(note_lifecycle, "_index", AsyncMock()) as reindex,
    ):
        compensated = await note_lifecycle.delete("note-1")
    assert compensated["success"] is False
    assert compensated["stage"] == "sqlite"
    assert compensated["compensated"] is True
    restore.assert_called_once_with(NOTE)
    reindex.assert_awaited_once_with(NOTE)

    with (
        patch.object(note_lifecycle.db, "get_note", return_value=NOTE),
        patch.object(note_lifecycle, "_delete_index", AsyncMock()),
        patch.object(note_lifecycle.db, "delete_note", side_effect=OSError("db")),
        patch.object(note_lifecycle.db, "restore_note", side_effect=OSError("restore")),
    ):
        uncompensated = await note_lifecycle.delete("note-1")
    assert uncompensated["compensated"] is False
    assert uncompensated["compensation_errors"] == ["OSError"]

    try:
        await notes_api.delete_note("note-1", confirmed=False)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("La suppression API devait exiger une confirmation explicite.")

    with patch.object(
        notes_api.note_lifecycle,
        "delete",
        AsyncMock(return_value={
            "success": False,
            "deleted": False,
            "stage": "qdrant",
            "error_type": "RuntimeError",
            "compensated": True,
        }),
    ):
        try:
            await notes_api.delete_note("note-1", confirmed=True)
        except HTTPException as exc:
            assert exc.status_code == 503
            assert exc.detail["stage"] == "qdrant"
        else:
            raise AssertionError("La panne Qdrant devait rester visible via HTTP 503.")


def main() -> int:
    asyncio.run(_run())
    print("Note Lifecycle OK - cohérence qualifiée, suppression stricte et compensation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
