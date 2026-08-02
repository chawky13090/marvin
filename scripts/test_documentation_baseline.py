"""Contrat statique des documents canoniques et des métriques d'architecture."""

from __future__ import annotations

import json
import re
from pathlib import Path

from check_architecture import fastapi_routes, tool_names


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def main() -> int:
    version_source = read("backend/app_version.py")
    match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', version_source)
    assert match, "APP_VERSION introuvable"
    version = match.group(1)

    package_version = json.loads(read("package.json"))["version"]
    registry, specs = tool_names()
    tool_count = len(registry)
    route_count = len(fastapi_routes())
    main_lines = len(read("backend/main.py").splitlines())

    assert len(registry) == len(set(registry)), "TOOLS_REGISTRY contient un doublon"
    assert len(specs) == len(set(specs)), "TOOLS_SPEC contient un doublon"
    assert set(registry) == set(specs), "registre et schémas d'outils divergent"
    assert package_version == version
    assert main_lines <= 400, f"main.py redevient monolithique: {main_lines} lignes"

    agents = read("AGENTS.md")
    claude = read("CLAUDE.md")
    architecture = read("ARCHITECTURE.md")
    debt = read("docs/TECHNICAL-DEBT.md")
    readme = read("README.md")

    for name, content in (("AGENTS.md", agents), ("CLAUDE.md", claude)):
        assert version in content, f"{name}: version courante absente"
        assert f"{tool_count} outils" in content, f"{name}: nombre d'outils périmé"
        assert f"{route_count} routes" in content, f"{name}: nombre de routes périmé"
        assert "docs/TECHNICAL-DEBT.md" in content, f"{name}: registre de dette absent"

    active_claude = claude.split("## Historique", 1)[0]
    for stale in ("261 outils", "Version backend** : `2.80.0`", "tous les endpoints FastAPI"):
        assert stale not in active_claude, f"CLAUDE.md actif contient encore: {stale}"

    assert f'TOOLS["{tool_count} outils"]' in architecture
    assert "aucune route métier" in architecture
    assert "TD-001" in debt and "TD-007" in debt
    assert "TECHNICAL-DEBT.md" in readme

    print(
        "Documentation baseline OK - "
        f"Marvin {version}, {tool_count} outils, {route_count} routes, "
        f"main.py {main_lines} lignes et dette explicite."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
