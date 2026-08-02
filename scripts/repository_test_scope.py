"""Frontiere unique des sources de premier niveau inspectees par les tests statiques."""

from __future__ import annotations

from pathlib import Path


EXCLUDED_BACKEND_PARTS = {"__pycache__", "data", "generated_videos"}


def is_backend_source(path: Path, backend_root: Path) -> bool:
    """Retourne vrai uniquement pour un fichier source appartenant au backend Marvin."""
    try:
        parts = path.resolve().relative_to(backend_root.resolve()).parts
    except ValueError:
        return False
    return not any(
        part in EXCLUDED_BACKEND_PARTS or part.startswith(".venv")
        for part in parts
    )


def backend_python_files(backend_root: Path) -> list[Path]:
    return [
        path
        for path in backend_root.rglob("*.py")
        if is_backend_source(path, backend_root)
    ]
