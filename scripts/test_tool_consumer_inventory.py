"""Inventorie les consommateurs qui n'ont pas encore migré vers tool_runtime."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
EXPECTED_DIRECT_CONSUMERS = {
    "agent.py": 1,
    "api/content.py": 9,
    "api/documents.py": 7,
    "api/email_automation.py": 1,
    "api/email_preferences.py": 2,
    "api/proactive.py": 1,
    "api/system_tools.py": 20,
    "communication_workers.py": 5,
    "proactive_service.py": 2,
}


def is_registry(value: ast.expr) -> bool:
    if isinstance(value, ast.Name):
        return value.id == "TOOLS_REGISTRY"
    return isinstance(value, ast.Attribute) and value.attr == "TOOLS_REGISTRY"


def inventory() -> dict[str, int]:
    result = {}
    for path in BACKEND.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript) and is_registry(node.value)
        )
        if count:
            result[path.relative_to(BACKEND).as_posix()] = count
    return dict(sorted(result.items()))


def main() -> int:
    observed = inventory()
    assert observed == EXPECTED_DIRECT_CONSUMERS, (
        "La dette des consommateurs directs a dérivé. Migrez vers tool_runtime ou "
        f"documentez explicitement le nouvel état : {observed}"
    )
    assert "api/calendar.py" not in observed
    assert sum(observed.values()) == 48
    print("Tool Consumer Inventory OK - agenda migré, dette restante bornée à 48 appels.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
