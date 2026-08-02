"""Interdit les connexions SQLite directes dont la fermeture n'est pas garantie."""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path

from repository_test_scope import backend_python_files


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
import sys

sys.path.insert(0, str(BACKEND))

from db_connection import get_conn


def main() -> int:
    violations: list[str] = []
    for path in backend_python_files(BACKEND):
        if path.name == "db_connection.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if isinstance(function, ast.Attribute) and function.attr == "get_conn":
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            elif isinstance(function, ast.Name) and function.id == "get_conn":
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not violations, "Connexions directes non bornees : " + ", ".join(violations)
    with tempfile.TemporaryDirectory() as directory:
        connection = get_conn(Path(directory) / "hygiene.db")
        try:
            assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert connection.execute("PRAGMA secure_delete").fetchone()[0] == 1
            assert connection.execute("PRAGMA trusted_schema").fetchone()[0] == 0
            assert connection.execute("PRAGMA cell_size_check").fetchone()[0] == 1
        finally:
            connection.close()
    print(
        "Hygiene SQLite OK - connexions bornees, effacement securise et schema non fiable."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
