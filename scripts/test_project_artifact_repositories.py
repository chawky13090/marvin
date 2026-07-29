"""Régressions SQLite des repositories projets, captures et logos."""

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
from repositories.logos import LogoRepository
from repositories.projects import ProjectRepository
from repositories.screenshots import ScreenshotRepository


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "artifacts.db"
        scope = lambda: db(path)
        projects = ProjectRepository(connection_scope=scope)
        screenshots = ScreenshotRepository(connection_scope=scope)
        logos = LogoRepository(connection_scope=scope)

        with patch("repositories.projects.uuid.uuid4", return_value="project-1"):
            project = projects.create("Migration", "Toujours tester.")
        assert project["instructions"] == "Toujours tester."
        assert projects.list_all()[0]["id"] == "project-1"
        updated = projects.update(
            "project-1",
            name="Migration validée",
            instructions="Tester et documenter.",
        )
        assert updated["name"] == "Migration validée"
        assert updated["instructions"] == "Tester et documenter."
        assert projects.update("missing", name="absent") is None
        assert projects.update("project-1", name="  Projet lisible  ")["name"] == "Projet lisible"
        for invalid_name in ("", "   ", "x" * 121):
            try:
                projects.update("project-1", name=invalid_name)
            except ValueError:
                pass
            else:
                raise AssertionError("Un nom de projet invalide doit être refusé.")

        with db(path) as connection:
            connection.execute(
                """CREATE TABLE conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    project_id TEXT,
                    FOREIGN KEY (project_id)
                        REFERENCES projects(id) ON DELETE SET NULL
                )"""
            )
            connection.execute(
                "INSERT INTO conversations (id, title, project_id) VALUES (?, ?, ?)",
                ("conversation-1", "Test", "project-1"),
            )

        with patch("repositories.screenshots.uuid.uuid4", return_value="shot-1"):
            screenshot = screenshots.create(
                "conversation-1",
                "C:/captures/test.png",
                caption="Console",
                ocr_text="commande",
            )
        assert screenshot["caption"] == "Console"
        assert screenshots.list("conversation-1", limit=10)[0]["id"] == "shot-1"
        assert screenshots.list("unknown", limit=10) == []
        assert screenshots.list(limit=10)[0]["id"] == "shot-1"

        with patch("repositories.logos.uuid.uuid4", return_value="logo-1"):
            logo = logos.create("Client", "Marque bleue", "C:/logos/client.png")
        assert logo["prompt"] == "Marque bleue"
        assert logos.list(limit=10)[0]["id"] == "logo-1"

        with patch("repositories.projects.uuid.uuid4", return_value="project-1"):
            try:
                projects.create("Collision")
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("Une clé projet dupliquée doit annuler la transaction.")
        assert projects.get("project-1")["name"] == "Projet lisible"

        projects.delete("project-1")
        assert projects.get("project-1") is None
        with db(path) as connection:
            linked = connection.execute(
                "SELECT project_id FROM conversations WHERE id = ?",
                ("conversation-1",),
            ).fetchone()
        assert linked["project_id"] is None

        legacy_path = root / "legacy-projects.db"
        with db(legacy_path) as connection:
            connection.execute(
                """CREATE TABLE projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
        legacy = ProjectRepository(connection_scope=lambda: db(legacy_path))
        assert legacy.list_all() == []
        with db(legacy_path) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(projects)").fetchall()
            }
        assert "instructions" in columns

    import database
    from repositories import logos as logo_module
    from repositories import projects as project_module
    from repositories import screenshots as screenshot_module

    expected = {
        "get_projects": project_module.get_projects,
        "get_project": project_module.get_project,
        "create_project": project_module.create_project,
        "update_project": project_module.update_project,
        "delete_project": project_module.delete_project,
        "create_screenshot": screenshot_module.create_screenshot,
        "list_screenshots": screenshot_module.list_screenshots,
        "create_logo": logo_module.create_logo,
        "list_logos": logo_module.list_logos,
    }
    for name, function in expected.items():
        assert getattr(database, name) is function, name

    print(
        "Project Artifact Repositories OK - projets, migration, FK, captures, "
        "logos, rollback et façades."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
