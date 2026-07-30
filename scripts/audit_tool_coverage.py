"""Inventaire reproductible des preuves disponibles pour chaque outil Marvin.

Ce contrôle n'exécute aucun outil. Il rapproche le catalogue public, le registre,
les politiques d'effet, les sondes réelles sûres et les tests automatisés.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools  # noqa: E402
from config import (  # noqa: E402
    CONDITIONAL_TOOL_SAFE_ACTIONS,
    DANGEROUS_TOOLS,
    SECURE_BLOCKED_TOOLS,
)
from tool_domains.system_self_test import SAFE_PROBES  # noqa: E402


@dataclass(frozen=True, slots=True)
class ToolCoverage:
    name: str
    executor_module: str
    schema: bool
    executor: bool
    harness: bool
    automated_test: bool
    test_files: tuple[str, ...]
    safe_live_probe: bool
    restricted: bool
    dangerous: bool
    conditional: bool
    workspace_excluded: bool


def _test_sources() -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): path.read_text(
            encoding="utf-8", errors="replace"
        )
        for path in sorted((ROOT / "scripts").glob("test_*"))
        if path.is_file() and path.suffix in {".py", ".mjs", ".js"}
    }


def _module_tokens(module_name: str) -> tuple[str, ...]:
    leaf = module_name.rsplit(".", 1)[-1]
    tokens = {module_name, leaf}
    if leaf.startswith("tool_domains."):
        tokens.add(leaf.removeprefix("tool_domains."))
    return tuple(token for token in tokens if len(token) >= 3)


def build_report() -> dict[str, Any]:
    specifications = {
        str(item.get("function", {}).get("name")): item
        for item in tools.TOOLS_SPEC
        if item.get("function", {}).get("name")
    }
    registry = dict(tools.TOOLS_REGISTRY)
    names = sorted(set(specifications) | set(registry))
    safe_probes = {probe.tool for probe in SAFE_PROBES}
    restricted_names = (
        set(DANGEROUS_TOOLS)
        | set(SECURE_BLOCKED_TOOLS)
        | set(CONDITIONAL_TOOL_SAFE_ACTIONS)
    )
    tests = _test_sources()
    rows: list[ToolCoverage] = []
    for name in names:
        executor = registry.get(name)
        module_name = str(getattr(executor, "__module__", "")) if executor else ""
        executor_name = str(getattr(executor, "__name__", "")) if executor else ""
        direct_needles = (
            f'"{name}"',
            f"'{name}'",
            f"`{name}`",
            f"execute_{name}",
        )
        if executor_name:
            direct_needles += (f".{executor_name}(", f" {executor_name}(")
        module_needles = _module_tokens(module_name)
        matching = tuple(
            path
            for path, source in tests.items()
            if any(needle in source for needle in direct_needles)
            or (
                module_needles
                and any(token in source for token in module_needles)
                and (
                    "TOOLS_REGISTRY" in source
                    or "tools.execute_" in source
                    or "tools.TOOLS_" in source
                )
            )
        )
        workspace_excluded = (
            name.startswith("code_workspace_")
            or module_name in {"coding_workspace", "coding_service", "coding_jobs"}
        )
        rows.append(
            ToolCoverage(
                name=name,
                executor_module=module_name,
                schema=name in specifications,
                executor=name in registry,
                harness=name in specifications and name in registry,
                automated_test=bool(matching),
                test_files=matching,
                safe_live_probe=name in safe_probes,
                restricted=name in restricted_names,
                dangerous=name in DANGEROUS_TOOLS,
                conditional=name in CONDITIONAL_TOOL_SAFE_ACTIONS,
                workspace_excluded=workspace_excluded,
            )
        )
    in_scope = [row for row in rows if not row.workspace_excluded]
    uncovered = [row.name for row in in_scope if not row.automated_test]
    return {
        "catalog_total": len(rows),
        "in_scope_total": len(in_scope),
        "workspace_excluded": sum(row.workspace_excluded for row in rows),
        "schema_and_executor": sum(row.harness for row in in_scope),
        "automated_test": sum(row.automated_test for row in in_scope),
        "safe_live_probe": sum(row.safe_live_probe for row in in_scope),
        "restricted": sum(row.restricted for row in in_scope),
        "dangerous": sum(row.dangerous for row in in_scope),
        "conditional": sum(row.conditional for row in in_scope),
        "uncovered_count": len(uncovered),
        "uncovered": uncovered,
        "tools": [asdict(row) for row in rows],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inventorie les preuves de couverture des outils Marvin."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Écrit aussi le rapport JSON à cet emplacement.",
    )
    args = parser.parse_args()
    report = build_report()
    if args.output:
        destination = args.output.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    summary = {
        key: value
        for key, value in report.items()
        if key not in {"tools", "uncovered"}
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if report["uncovered"]:
        print("Sans preuve automatisée directe ou par domaine :")
        print(", ".join(report["uncovered"]))
    return 0 if report["schema_and_executor"] == report["in_scope_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
