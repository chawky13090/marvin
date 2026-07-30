from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from agent_tool_step import inject_internal_context  # noqa: E402
from tool_domains import workspace_organization as organization  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_project_create_is_idempotent_by_name() -> None:
    existing = {"id": "p1", "name": "Loïc", "instructions": ""}
    with patch.object(organization.db, "get_projects", return_value=[existing]), patch.object(
        organization.db, "create_project"
    ) as create:
        result = run(organization.execute_project_create({"name": " loïc "}))
    assert result["success"] is True
    assert result["already_exists"] is True
    assert result["project"]["id"] == "p1"
    create.assert_not_called()


def test_project_create_returns_compensation() -> None:
    created = {"id": "p2", "name": "Alpha", "instructions": "Rester concis"}
    with patch.object(organization.db, "get_projects", return_value=[]), patch.object(
        organization.db, "create_project", return_value=created
    ):
        result = run(
            organization.execute_project_create(
                {"name": "Alpha", "instructions": "Rester concis"}
            )
        )
    assert result["success"] is True
    assert result["rollback"]["tool"] == "project_delete"
    assert result["ui_refresh"] == ["projects", "conversations"]


def test_move_current_conversation_to_named_project() -> None:
    conversation = {"id": "c1", "title": "Discussion", "project_id": None}
    project = {"id": "p1", "name": "Loïc", "instructions": ""}
    updated = {**conversation, "project_id": "p1"}
    with patch.object(organization.db, "get_conversation", side_effect=[conversation, updated]), patch.object(
        organization.db, "get_projects", return_value=[project]
    ), patch.object(organization.db, "update_conversation_project") as move:
        result = run(
            organization.execute_conversation_move(
                {"_conversation_id": "c1", "project_name": "Loïc"}
            )
        )
    move.assert_called_once_with("c1", "p1")
    assert result["success"] is True
    assert result["conversation"]["project_id"] == "p1"
    assert result["rollback"]["arguments"]["remove_from_project"] is True


def test_ambiguous_title_never_moves() -> None:
    matches = [
        {"id": "c1", "title": "Debian", "project_id": None},
        {"id": "c2", "title": "Debian", "project_id": None},
    ]
    with patch.object(organization.db, "search_conversations", return_value=matches), patch.object(
        organization.db, "update_conversation_project"
    ) as move:
        result = run(
            organization.execute_conversation_move(
                {"conversation_title": "Debian", "project_name": "Infra"}
            )
        )
    assert result["success"] is False
    assert result["requires_clarification"] is True
    assert len(result["matches"]) == 2
    move.assert_not_called()


def test_project_delete_requires_confirmation() -> None:
    with patch.object(organization.db, "delete_project") as delete:
        result = run(organization.execute_project_delete({"project_id": "p1"}))
    assert result["success"] is False
    assert result["requiresConfirmation"] is True
    delete.assert_not_called()


def test_bulk_move_rolls_back_after_partial_failure() -> None:
    conversations = {
        "c1": {"id": "c1", "title": "Un", "project_id": "old-1"},
        "c2": {"id": "c2", "title": "Deux", "project_id": "old-2"},
    }
    calls: list[tuple[str, str | None]] = []

    def move(conversation_id: str, project_id: str | None) -> None:
        calls.append((conversation_id, project_id))
        if conversation_id == "c2" and project_id == "new":
            raise RuntimeError("écriture simulée")

    with patch.object(
        organization.db,
        "get_conversation",
        side_effect=lambda conversation_id: conversations.get(conversation_id),
    ), patch.object(
        organization.db,
        "get_project",
        return_value={"id": "new", "name": "Nouveau", "instructions": ""},
    ), patch.object(organization.db, "update_conversation_project", side_effect=move):
        try:
            run(
                organization.execute_conversation_move_many(
                    {
                        "conversation_ids": ["c1", "c2"],
                        "project_id": "new",
                    }
                )
            )
        except RuntimeError:
            pass
    assert calls == [("c1", "new"), ("c2", "new"), ("c1", "old-1")]


def test_current_conversation_context_is_server_injected() -> None:
    arguments = inject_internal_context("conversation_move", {"project_name": "Loïc"}, "c1")
    assert arguments["_conversation_id"] == "c1"
    explicit = inject_internal_context(
        "conversation_move",
        {"conversation_id": "c2", "project_name": "Loïc"},
        "c1",
    )
    assert "_conversation_id" not in explicit


if __name__ == "__main__":
    test_project_create_is_idempotent_by_name()
    test_project_create_returns_compensation()
    test_move_current_conversation_to_named_project()
    test_ambiguous_title_never_moves()
    test_project_delete_requires_confirmation()
    test_bulk_move_rolls_back_after_partial_failure()
    test_current_conversation_context_is_server_injected()
    print("workspace organization tests: ok")
