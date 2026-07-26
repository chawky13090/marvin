"""Régressions du repository transactionnel des workflows."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db_connection import db
from repositories.workflows import WorkflowRepository


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "workflows.db"
        repository = WorkflowRepository(connection_scope=lambda: db(path))
        steps = [{"id": "s1", "tool_name": "calculator", "args": {"expression": "1+1"}}]
        with patch("repositories.workflows.uuid.uuid4", return_value="workflow-1"):
            created = repository.create_workflow("Calcul", "Test", steps)
        assert created["steps"] == steps and created["run_count"] == 0
        assert repository.list_workflows()[0]["id"] == "workflow-1"

        updated = repository.update_workflow(
            "workflow-1", {"name": "Calcul validé", "run_count": True, "forbidden": "x"}
        )
        assert updated["name"] == "Calcul validé" and updated["run_count"] == 1
        assert "forbidden" not in updated

        with patch("repositories.workflows.uuid.uuid4", return_value="run-1"):
            run = repository.create_run("workflow-1")
        assert run["status"] == "running" and run["steps_results"] == []
        result_steps = [{"step_id": "s1", "success": True}]
        finished = repository.finish_run("run-1", "success", result_steps, 42)
        assert finished["steps_results"] == result_steps and finished["duration_ms"] == 42
        assert repository.list_runs("workflow-1", limit=999)[0]["id"] == "run-1"

        with db(path) as connection:
            connection.execute(
                "UPDATE workflows SET steps='invalid-json' WHERE id='workflow-1'"
            )
        assert repository.get_workflow("workflow-1")["steps"] == []

        with patch("repositories.workflows.uuid.uuid4", return_value="workflow-1"):
            try:
                repository.create_workflow("Duplicate", "", [])
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("La clé primaire doit provoquer un rollback")
        assert repository.get_workflow("workflow-1")["name"] == "Calcul validé"

        repository.delete_workflow("workflow-1")
        assert repository.get_workflow("workflow-1") is None
        assert repository.list_runs("workflow-1") == []

    import database
    from repositories import workflows

    assert database.create_workflow is workflows.create_workflow
    assert database.finish_workflow_run is workflows.finish_workflow_run
    assert database.list_workflow_runs is workflows.list_workflow_runs
    print("Workflow Repository OK - CRUD, JSON, runs, bornes, cascade et rollback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
