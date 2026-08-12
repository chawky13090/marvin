"""Analyse statique hybride des effets persistants des contrats E7 directs.

Le backend n'est jamais importé et aucun outil n'est exécuté. L'analyse travaille uniquement
sur les AST, suit les alias et appels internes, puis applique les règles JSON gelées.
"""
from __future__ import annotations

import ast
import builtins
import fnmatch
import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.3"
RULES_PATH = BASE / "surface-analysis-rules.json"
POLICY_PATH = BASE / "surface-analysis-preregistration.json"
CONTRACTS_PATH = ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "direct-fixture-contracts.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module_name(path: Path, root: Path = BACKEND) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted(node.value)
        return f"{prefix}.{node.attr}" if prefix else None
    return None


def imported_name(module: str | None, level: int, name: str, current: str) -> str:
    if level == 0:
        return f"{module}.{name}" if module else name
    package = current.split(".")[:-1]
    keep = max(0, len(package) - level + 1)
    prefix = package[:keep]
    if module:
        prefix.extend(module.split("."))
    prefix.append(name)
    return ".".join(prefix)


@dataclass
class FunctionInfo:
    qualified: str
    module: str
    name: str
    path: Path
    node: ast.FunctionDef | ast.AsyncFunctionDef
    imports: dict[str, str]
    locals: set[str]
    nested_callables: set[str]

    @property
    def label(self) -> str:
        return f"{self.path.relative_to(ROOT).as_posix()}:{self.name}"


@dataclass
class Analysis:
    entrypoint: str
    effects: set[str] = field(default_factory=set)
    paths: list[list[str]] = field(default_factory=list)
    unresolved: list[dict[str, object]] = field(default_factory=list)
    visited: set[str] = field(default_factory=set)


class ProjectIndex:
    def __init__(self, paths: Iterable[Path], *, source_root: Path = BACKEND) -> None:
        self.source_root = source_root
        self.modules: set[str] = set()
        self.functions: dict[str, FunctionInfo] = {}
        self.aliases: dict[str, str] = {}
        self.classes: set[str] = set()
        self.injected: set[str] = set()
        self.source_hashes: dict[str, str] = {}
        for path in sorted(paths):
            self._add(path)

    @classmethod
    def backend(cls) -> "ProjectIndex":
        completed = subprocess.run(
            ["git", "ls-files", "backend/**/*.py", "backend/*.py"],
            cwd=ROOT, capture_output=True, text=True, errors="replace", check=True,
        )
        paths = [ROOT / line for line in completed.stdout.splitlines() if line.strip()]
        return cls(paths)

    def _add(self, path: Path) -> None:
        module = module_name(path, self.source_root)
        self.modules.add(module)
        relative = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
        self.source_hashes[relative] = sha256(path)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        module_imports = self._imports(tree.body, module)
        for item in tree.body:
            if isinstance(item, ast.ClassDef):
                self.classes.add(f"{module}.{item.name}")
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(item):
                    if isinstance(node, ast.Global):
                        self.injected.update(f"{module}.{name}" for name in node.names)
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    self.aliases[f"{module}.{local_name}"] = imported_name(
                        node.module, node.level, alias.name, module
                    )
        for item in tree.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                imports = dict(module_imports)
                imports.update(self._imports(item.body, module))
                local_names = {
                    arg.arg
                    for arg in [*item.args.posonlyargs, *item.args.args, *item.args.kwonlyargs]
                }
                if item.args.vararg:
                    local_names.add(item.args.vararg.arg)
                if item.args.kwarg:
                    local_names.add(item.args.kwarg.arg)
                local_names.update(
                    node.id for node in ast.walk(item)
                    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
                )
                nested_callables = {
                    node.name for node in ast.walk(item)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node is not item
                }
                local_names.update(nested_callables)
                qualified = f"{module}.{item.name}"
                self.functions[qualified] = FunctionInfo(
                    qualified, module, item.name, path, item, imports, local_names, nested_callables
                )
            elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                value = item.value
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                resolved = self._resolve_expression(value, module, module_imports)
                if resolved:
                    for target in targets:
                        if isinstance(target, ast.Name):
                            self.aliases[f"{module}.{target.id}"] = resolved

    @staticmethod
    def _imports(nodes: list[ast.stmt], current: str) -> dict[str, str]:
        found: dict[str, str] = {}
        for node in ast.walk(ast.Module(body=nodes, type_ignores=[])):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found[alias.asname or alias.name.split(".")[0]] = alias.name
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    found[alias.asname or alias.name] = imported_name(node.module, node.level, alias.name, current)
        return found

    def _resolve_expression(
        self,
        node: ast.AST | None,
        current: str,
        imports: dict[str, str],
        local_names: set[str] | None = None,
    ) -> str | None:
        raw = dotted(node) if node is not None else None
        if not raw:
            return None
        head, *tail = raw.split(".")
        if local_names and head in local_names:
            return None
        if head in imports:
            return ".".join([imports[head], *tail])
        if head in dir(builtins):
            return f"builtins.{raw}"
        local = f"{current}.{raw}"
        if local in self.injected:
            return f"@injected:{local}"
        return self.aliases.get(local, local)

    def resolve_call(self, node: ast.AST, info: FunctionInfo) -> str | None:
        return self._resolve_expression(node, info.module, info.imports, info.locals)

    def tool_entrypoint(self, tool: str) -> str | None:
        alias = self.aliases.get(f"tools.execute_{tool}")
        if alias is None and f"tools.execute_{tool}" in self.functions:
            return f"tools.execute_{tool}"
        seen: set[str] = set()
        while alias in self.aliases and alias not in seen:
            seen.add(alias)
            alias = self.aliases[alias]
        return alias


def _matches(target: str, rule: dict[str, object]) -> bool:
    prefixes = rule["module_prefixes"]
    for prefix in prefixes:
        if target == prefix or target.startswith(f"{prefix}."):
            call = target[len(prefix):].lstrip(".") or "*"
            return any(fnmatch.fnmatch(call, pattern) for pattern in rule["call_patterns"])
    return False


def _is_read_only(target: str, rules: dict[str, object]) -> bool:
    for prefix, patterns in rules.get("read_only_exceptions", {}).items():
        if target.startswith(f"{prefix}."):
            call = target[len(prefix) + 1:]
            return any(fnmatch.fnmatch(call, pattern) for pattern in patterns)
    return False


def sink_effects(target: str, rules: dict[str, object]) -> set[str]:
    if _is_read_only(target, rules):
        return set()
    return {str(rule["effect"]) for rule in rules["sink_rules"] if _matches(target, rule)}


def is_sink_boundary(target: str, rules: dict[str, object]) -> bool:
    return any(_matches(target, rule) for rule in rules["sink_rules"])


def _dynamic_reason(node: ast.AST) -> str | None:
    if isinstance(node, ast.Subscript):
        return "subscript_callable"
    if isinstance(node, ast.Call):
        name = dotted(node.func)
        if name in {"getattr", "eval", "exec", "__import__", "importlib.import_module"}:
            return f"dynamic_callable:{name}"
    return None


def analyze(index: ProjectIndex, entrypoint: str, rules: dict[str, object]) -> Analysis:
    result = Analysis(entrypoint=entrypoint)

    def walk(function_name: str, path: list[str], depth: int) -> None:
        if depth > int(rules.get("maximum_call_depth", 32)):
            result.unresolved.append({"reason": "maximum_call_depth_reached", "path": path})
            result.effects.add("unknown")
            return
        if function_name in path:
            result.paths.append([*path, f"cycle:{function_name}"])
            return
        if function_name in result.visited:
            return
        info = index.functions.get(function_name)
        if info is None:
            result.unresolved.append({"reason": "entrypoint_not_found", "target": function_name, "path": path})
            result.effects.add("unknown")
            return
        result.visited.add(function_name)
        current_path = [*path, info.label]
        for node in ast.walk(info.node):
            if not isinstance(node, ast.Call):
                continue
            dynamic = _dynamic_reason(node.func)
            if dynamic:
                result.effects.add("unknown")
                result.unresolved.append({"reason": dynamic, "line": node.lineno, "path": current_path})
                continue
            target = index.resolve_call(node.func, info)
            if not target:
                raw = dotted(node.func)
                head = raw.split(".", 1)[0] if raw else None
                if isinstance(node.func, ast.Name) and head in info.locals:
                    if head in info.nested_callables:
                        continue
                    result.effects.add("unknown")
                    result.unresolved.append({"reason": "local_callable_unresolved", "line": node.lineno, "path": current_path})
                continue
            effects = sink_effects(target, rules)
            if effects:
                result.effects.update(effects)
                result.paths.append([*current_path, f"sink:{target}"])
            if is_sink_boundary(target, rules):
                continue
            if target.startswith("@injected:"):
                result.effects.add("unknown")
                result.unresolved.append({"reason": "runtime_injected_callable", "target": target[10:], "line": node.lineno, "path": current_path})
                continue
            if target in rules.get("transparent_call_wrappers", []):
                if not node.args:
                    result.effects.add("unknown")
                    result.unresolved.append({"reason": "transparent_wrapper_without_callable", "target": target, "line": node.lineno, "path": current_path})
                    continue
                wrapped = index.resolve_call(node.args[0], info)
                if wrapped in index.aliases:
                    wrapped = index.aliases[wrapped]
                wrapped_effects = sink_effects(wrapped or "", rules)
                if wrapped_effects:
                    result.effects.update(wrapped_effects)
                    result.paths.append([*current_path, f"sink:{wrapped}"])
                elif wrapped in index.functions:
                    walk(wrapped, current_path, depth + 1)
                else:
                    result.effects.add("unknown")
                    result.unresolved.append({"reason": "wrapped_callable_unresolved", "target": wrapped, "line": node.lineno, "path": current_path})
                continue
            aliased_target = index.aliases.get(target, target)
            if aliased_target in index.functions:
                walk(aliased_target, current_path, depth + 1)
            elif target in index.functions:
                walk(target, current_path, depth + 1)
            elif target in index.classes:
                continue
            elif any(target == module or target.startswith(f"{module}.") for module in index.modules):
                result.effects.add("unknown")
                result.unresolved.append({"reason": "unresolved_project_call", "target": target, "line": node.lineno, "path": current_path})

    walk(entrypoint, [], 0)
    return result


def verdict(observed: set[str], declared: set[str], unresolved: bool) -> str:
    confirmed = observed - {"unknown"}
    if confirmed - declared:
        return "UNDER_DECLARED"
    if unresolved or "unknown" in observed:
        return "UNKNOWN"
    if declared - confirmed:
        return "UNKNOWN"
    return "CONFIRMED"


def analyze_contracts() -> dict[str, object]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    contracts = json.loads(CONTRACTS_PATH.read_text(encoding="utf-8"))["contracts"]
    index = ProjectIndex.backend()
    results: list[dict[str, object]] = []
    counts: dict[str, int] = {}
    for contract in contracts:
        entrypoint = index.tool_entrypoint(contract["tool"])
        if entrypoint is None:
            analysis = Analysis(entrypoint="")
            analysis.effects.add("unknown")
            analysis.unresolved.append({"reason": "tool_alias_not_found", "tool": contract["tool"]})
        else:
            analysis = analyze(index, entrypoint, {**rules, "maximum_call_depth": policy["analysis_contract"]["maximum_call_depth"]})
        declared = set(rules["declared_surface_effects"][contract["surface_profile"]])
        state = verdict(analysis.effects, declared, bool(analysis.unresolved))
        counts[state] = counts.get(state, 0) + 1
        results.append({
            "contract_id": contract["id"],
            "tool": contract["tool"],
            "action": contract["action"],
            "declared_surface": contract["surface_profile"],
            "declared_effects": sorted(declared),
            "entrypoint": entrypoint,
            "state": state,
            "confirmed_effects": sorted(analysis.effects - {"unknown"}),
            "unknown": bool(analysis.unresolved),
            "paths": analysis.paths,
            "unresolved_paths": analysis.unresolved,
            "visited_functions": sorted(analysis.visited),
        })
    return {
        "schema": "marvin.e7-direct-surface-analysis/1.0",
        "status": "static_analysis_published_contracts_unchanged",
        "tool_execution_performed": False,
        "contract_mutation_performed": False,
        "contracts": len(results),
        "counts": counts,
        "policy_sha256": sha256(POLICY_PATH),
        "rules_sha256": sha256(RULES_PATH),
        "analyzer_sha256": sha256(ROOT / "scripts" / "e7_surface_analyzer.py"),
        "contracts_sha256": sha256(CONTRACTS_PATH),
        "source_hashes": index.source_hashes,
        "results": results,
        "limitations": [
            "static_analysis_does_not_prove_runtime_branch_coverage",
            "unknown_is_preserved_for_dynamic_or_unresolved_project_calls",
            "sink_rules_are_frozen_before_implementation"
        ]
    }


def main() -> int:
    output = analyze_contracts()
    destination = BASE / "direct-surface-analysis.json"
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"E7 Surface Analysis - {output['contracts']} contracts | {output['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
