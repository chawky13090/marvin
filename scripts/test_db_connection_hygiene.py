"""Interdit les connexions SQLite directes dont la fermeture n'est pas garantie."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> int:
    violations: list[str] = []
    for path in BACKEND.rglob("*.py"):
        if ".venv" in path.parts or path.name == "db_connection.py":
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
    print("Hygiene SQLite OK - aucune connexion directe hors de la fabrique.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
