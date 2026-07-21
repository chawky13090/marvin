"""Create portable, isolated Git repositories for prompt-first coding missions."""
from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import repository_intelligence
import storage_layout


class ScratchRepositoryError(RuntimeError):
    pass


def _run(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScratchRepositoryError(f"Git indisponible : {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[:1_000]
        raise ScratchRepositoryError(detail or "Git a refusé la création du projet isolé.")
    return result.stdout.strip()


def _slug(request: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", request.casefold()).strip("-")
    return (value[:48].rstrip("-") or "nouveau-projet")


def create(request: str, *, confirmed: bool) -> dict[str, Any]:
    """Create one clean Git repository below Marvin's machine-local workspace root."""
    cleaned = str(request or "").strip()
    if len(cleaned) < 3:
        raise ScratchRepositoryError("La demande de code doit contenir au moins trois caractères.")
    if not confirmed:
        raise ScratchRepositoryError("La création du projet isolé doit être confirmée.")

    storage_layout.ensure(confirmed=True)
    machine_root, _ = storage_layout.roots()
    parent = (machine_root / "workspaces" / "code" / "requests").resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = (parent / f"{_slug(cleaned)}-{uuid.uuid4().hex[:8]}").resolve()
    try:
        root.relative_to(parent)
    except ValueError as exc:
        raise ScratchRepositoryError("Le projet calculé sort de la bibliothèque Marvin.") from exc

    root.mkdir(parents=False, exist_ok=False)
    try:
        (root / "README.md").write_text(
            "# Projet Code Workspace\n\n"
            "Dépôt isolé créé automatiquement par Marvin pour une demande sans dépôt existant.\n",
            encoding="utf-8", newline="\n",
        )
        (root / ".gitignore").write_text(
            ".env\n.env.*\n*.key\n*.pem\nnode_modules/\n.venv/\n__pycache__/\n"
            "dist/\nbuild/\ncoverage/\n",
            encoding="utf-8", newline="\n",
        )
        _run(root, "init", "--initial-branch=main")
        _run(root, "add", "README.md", ".gitignore")
        _run(
            root, "-c", "user.name=Marvin", "-c", "user.email=marvin@localhost",
            "commit", "-m", "Initialisation du projet Code Workspace",
        )
        return repository_intelligence.inspect(str(root))
    except Exception:
        try:
            root.relative_to(parent)
            shutil.rmtree(root, ignore_errors=True)
        except ValueError:
            pass
        raise
