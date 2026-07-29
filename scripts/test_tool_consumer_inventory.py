"""Inventorie les consommateurs qui n'ont pas encore migré vers tool_runtime."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
EXPECTED_DIRECT_CONSUMERS = {
    "agent.py": 1,
    "api/system_tools.py": 25,
}


def is_registry(value: ast.expr) -> bool:
    if isinstance(value, ast.Name):
        return value.id == "TOOLS_REGISTRY"
    return isinstance(value, ast.Attribute) and value.attr == "TOOLS_REGISTRY"


def registry_aliases(tree: ast.AST) -> set[str]:
    aliases = {"TOOLS_REGISTRY"}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None or not (
                is_registry(value)
                or isinstance(value, ast.Name) and value.id in aliases
            ):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    changed = True
    return aliases


def is_registry_access(value: ast.expr, aliases: set[str]) -> bool:
    return is_registry(value) or isinstance(value, ast.Name) and value.id in aliases


def inventory() -> dict[str, int]:
    result = {}
    for path in BACKEND.rglob("*.py"):
        if any(part in {".venv", "__pycache__"} for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        aliases = registry_aliases(tree)
        count = sum(
            1
            for node in ast.walk(tree)
            if (
                isinstance(node, ast.Subscript)
                and is_registry_access(node.value, aliases)
            )
            or (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and is_registry_access(node.func.value, aliases)
            )
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
    assert "api/proactive.py" not in observed
    assert "proactive_service.py" not in observed
    assert "api/multi_agents.py" not in observed
    assert "api/workflows.py" not in observed
    assert "cron_runtime.py" not in observed
    assert "api/email_automation.py" not in observed
    assert "api/email_preferences.py" not in observed
    assert "communication_workers.py" not in observed
    assert "api/content.py" not in observed
    assert "api/documents.py" not in observed
    assert sum(observed.values()) == 26
    print("Tool Consumer Inventory OK - contenu/documents migrés, dette bornée à 26 accès.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
