"""Analyse E7 v1.4 sensible aux chemins, sans importer ni executer Marvin."""
from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from e7_surface_analyzer import (
    ROOT, ProjectIndex, FunctionInfo, dotted, is_sink_boundary, sha256, sink_effects,
)

BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.4"
V13_BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.3"
POLICY_PATH = BASE / "path-analysis-preregistration.json"
RULES_PATH = BASE / "path-analysis-rules.json"
V13_RULES_PATH = V13_BASE / "surface-analysis-rules.json"
V13_RESULT_PATH = V13_BASE / "direct-surface-analysis.json"
CONTRACTS_PATH = ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "direct-fixture-contracts.json"
UNKNOWN = object()


def _stable(value: object) -> object:
    if value is UNKNOWN:
        return "<UNKNOWN>"
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return "<OBJECT>"


def _args_get(node: ast.AST) -> tuple[str, ast.AST | None] | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr != "get" or not isinstance(node.func.value, ast.Name) or node.func.value.id != "args":
        return None
    if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
        return None
    return node.args[0].value, node.args[1] if len(node.args) > 1 else None


def evaluate(node: ast.AST | None, env: dict[str, object]) -> object:
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id, UNKNOWN)
    getter = _args_get(node)
    if getter:
        key, default_node = getter
        args = env.get("args")
        if isinstance(args, dict):
            if key in args:
                return args[key]
            if args.get("__symbolic_payload__"):
                return UNKNOWN
            return evaluate(default_node, env)
        return UNKNOWN
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = evaluate(node.operand, env)
        return UNKNOWN if value is UNKNOWN else not bool(value)
    if isinstance(node, ast.BoolOp):
        values = [evaluate(item, env) for item in node.values]
        if isinstance(node.op, ast.And):
            for value in values:
                if value is UNKNOWN:
                    return UNKNOWN
                if not bool(value):
                    return value
            return values[-1] if values else True
        for value in values:
            if value is UNKNOWN:
                return UNKNOWN
            if bool(value):
                return value
        return values[-1] if values else False
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
        left, right = evaluate(node.left, env), evaluate(node.comparators[0], env)
        if left is UNKNOWN or right is UNKNOWN:
            return UNKNOWN
        op = node.ops[0]
        if isinstance(op, (ast.Eq, ast.Is)):
            return left == right
        if isinstance(op, (ast.NotEq, ast.IsNot)):
            return left != right
        if isinstance(op, (ast.In, ast.NotIn)):
            try:
                found = left in right
                return not found if isinstance(op, ast.NotIn) else found
            except TypeError:
                return UNKNOWN
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = [evaluate(item, env) for item in node.elts]
        return UNKNOWN if UNKNOWN in values else type(node.elts)(values) if False else tuple(values)
    if isinstance(node, ast.IfExp):
        condition = evaluate(node.test, env)
        if condition is True:
            return evaluate(node.body, env)
        if condition is False:
            return evaluate(node.orelse, env)
        return UNKNOWN
    if isinstance(node, ast.Call):
        name = dotted(node.func)
        args = [evaluate(item, env) for item in node.args]
        if name in {"str", "builtins.str"} and args and args[0] is not UNKNOWN:
            return str(args[0])
        if name in {"bool", "builtins.bool"} and args and args[0] is not UNKNOWN:
            return bool(args[0])
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"casefold", "lower", "strip"}:
            value = evaluate(node.func.value, env)
            if isinstance(value, str):
                return getattr(value, node.func.attr)()
    return UNKNOWN


def operation_for(target: str, effect: str, read_only: bool) -> str:
    call = target.rsplit(".", 1)[-1].casefold()
    if effect == "process":
        if target.startswith("psutil.") and call in {"pid_exists", "process_iter", "process", "is_running", "status", "create_time", "children", "connections", "net_connections"}:
            return "OBSERVE"
        return "EXECUTE"
    if read_only:
        return "OBSERVE" if effect in {"process", "service", "network"} else "READ"
    if any(token in call for token in ("delete", "remove", "unlink", "rmdir", "kill", "terminate")):
        return "DELETE"
    if any(token in call for token in ("create", "mkdir", "makedirs", "touch", "start", "launch", "popen")):
        return "CREATE" if effect not in {"process", "service"} else "EXECUTE"
    if effect in {"network", "external_provider"}:
        return "EXTERNAL_WRITE"
    if effect in {"process", "service"}:
        return "EXECUTE"
    return "UPDATE"


@dataclass
class PathResult:
    compatible: list[dict[str, object]] = field(default_factory=list)
    guarded: list[dict[str, object]] = field(default_factory=list)
    excluded: list[dict[str, object]] = field(default_factory=list)
    unresolved: list[dict[str, object]] = field(default_factory=list)
    visited: set[str] = field(default_factory=set)


class PathAnalyzer:
    def __init__(self, index: ProjectIndex, sink_rules: dict[str, object], path_rules: dict[str, object] | None = None) -> None:
        self.index = index
        self.sink_rules = sink_rules
        self.path_rules = path_rules or json.loads(RULES_PATH.read_text(encoding="utf-8"))
        self.result = PathResult()
        self.active: set[tuple[str, str]] = set()

    def _record(self, bucket: str, payload: dict[str, object]) -> None:
        getattr(self.result, bucket).append(payload)

    def _resolve_target(self, node: ast.AST, info: FunctionInfo, env: dict[str, object]) -> str | None:
        target = self.index.resolve_call(node, info)
        if target is not None:
            return target
        if not isinstance(node, ast.Attribute):
            return None
        if isinstance(node.value, ast.Name):
            typed = env.get(node.value.id)
            if isinstance(typed, str) and typed.startswith("@type:"):
                return f"{typed[6:]}.{node.attr}"
        if isinstance(node.value, ast.Call):
            base = self._resolve_target(node.value.func, info, env)
            if base:
                if base.startswith("pathlib.Path.") or base == "pathlib.Path":
                    return f"pathlib.Path.{node.attr}"
                if base.startswith("psutil.Process"):
                    return f"psutil.Process.{node.attr}"
                return f"{base}.{node.attr}"
        return None

    def _call(self, node: ast.Call, info: FunctionInfo, env: dict[str, object], path: list[str], guard: str) -> None:
        target = self._resolve_target(node.func, info, env)
        if not target:
            if isinstance(node.func, (ast.Subscript, ast.Call)) or (
                isinstance(node.func, ast.Name) and node.func.id in info.locals
            ):
                self._record("unresolved", {"reason": "dynamic_callable", "path": path, "line": node.lineno, "constraints": guard})
            return
        effects = sink_effects(target, self.sink_rules)
        psutil_call = target.removeprefix("psutil.").casefold()
        process_rules = self.path_rules["process_semantics"]
        if target.startswith("psutil.") and any(psutil_call.endswith(name.casefold()) for name in process_rules["psutil_observation_calls"]):
            effects = {"process"}
        if target.startswith("psutil.") and any(psutil_call.endswith(name.casefold()) for name in process_rules["psutil_mutation_calls"]):
            effects = {"process"}
        if effects:
            for effect in effects:
                observation = target.startswith("psutil.") and any(
                    psutil_call.endswith(name.casefold()) for name in process_rules["psutil_observation_calls"]
                )
                operation = "OBSERVE" if observation else operation_for(target, effect, False)
                self._record("compatible", {"effect": effect, "operation": operation, "target": target, "path": [*path, f"sink:{target}"], "constraints": guard})
        if is_sink_boundary(target, self.sink_rules):
            return
        if target.startswith("@injected:"):
            self._record("unresolved", {"reason": "runtime_injected_callable", "target": target[10:], "path": path, "line": node.lineno, "constraints": guard})
            return
        if target in self.sink_rules.get("transparent_call_wrappers", []):
            if not node.args:
                self._record("unresolved", {"reason": "wrapper_without_callable", "path": path, "line": node.lineno, "constraints": guard})
                return
            target = self.index.resolve_call(node.args[0], info) or ""
            call_args = node.args[1:]
        else:
            target = self.index.aliases.get(target, target)
            call_args = node.args
        callee = self.index.functions.get(target)
        if callee:
            child_env: dict[str, object] = {}
            params = [*callee.node.args.posonlyargs, *callee.node.args.args]
            for param, argument in zip(params, call_args):
                child_env[param.arg] = evaluate(argument, env)
            self.walk(target, child_env, path, guard)
        elif any(target == module or target.startswith(f"{module}.") for module in self.index.modules):
            self._record("unresolved", {"reason": "unresolved_project_call", "target": target, "path": path, "line": node.lineno, "constraints": guard})

    def _calls(self, node: ast.AST, info: FunctionInfo, env: dict[str, object], path: list[str], guard: str) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                self._call(child, info, env, path, guard)

    def _block(self, statements: list[ast.stmt], info: FunctionInfo, env: dict[str, object], path: list[str], guard: str) -> bool:
        for statement in statements:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                self._calls(statement.value, info, env, path, guard)
                value = evaluate(statement.value, env)
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        env[target.id] = value
                continue
            if isinstance(statement, ast.If):
                self._calls(statement.test, info, env, path, guard)
                value = evaluate(statement.test, env)
                condition = ast.unparse(statement.test)
                if value is True:
                    if self._block(statement.body, info, dict(env), path, f"{guard} AND ({condition})"):
                        return True
                elif value is False:
                    for node in statement.body:
                        self._record("excluded", {"reason": "condition_false", "condition": condition, "line": statement.lineno, "path": path})
                    if self._block(statement.orelse, info, dict(env), path, f"{guard} AND NOT ({condition})"):
                        return True
                else:
                    before = len(self.result.compatible)
                    self._block(statement.body, info, dict(env), path, f"{guard} AND UNKNOWN ({condition})")
                    moved = self.result.compatible[before:]
                    del self.result.compatible[before:]
                    self.result.guarded.extend({**item, "reason": "unresolved_guard"} for item in moved)
                    self._block(statement.orelse, info, dict(env), path, f"{guard} AND UNKNOWN NOT ({condition})")
                    self._record("unresolved", {"reason": "condition_unknown", "condition": condition, "line": statement.lineno, "path": path, "constraints": guard})
                continue
            if isinstance(statement, ast.Return):
                if statement.value:
                    self._calls(statement.value, info, env, path, guard)
                return True
            if isinstance(statement, ast.Try):
                self._block(statement.body, info, dict(env), path, guard)
                for handler in statement.handlers:
                    self._block(handler.body, info, dict(env), path, f"{guard} AND EXCEPTION")
                self._block(statement.orelse, info, dict(env), path, guard)
                self._block(statement.finalbody, info, dict(env), path, guard)
                continue
            if isinstance(statement, (ast.For, ast.While, ast.With, ast.AsyncWith)):
                body = statement.body
                self._block(body, info, dict(env), path, f"{guard} AND CONSERVATIVE_BLOCK")
                continue
            self._calls(statement, info, env, path, guard)
        return False

    def walk(self, function_name: str, env: dict[str, object], path: list[str] | None = None, guard: str = "TRUE") -> None:
        signature = json.dumps({key: _stable(value) for key, value in sorted(env.items())}, sort_keys=True)
        key = (function_name, signature)
        if key in self.active:
            return
        info = self.index.functions.get(function_name)
        if not info:
            self._record("unresolved", {"reason": "entrypoint_not_found", "target": function_name, "path": path or [], "constraints": guard})
            return
        self.active.add(key)
        self.result.visited.add(function_name)
        current = [*(path or []), info.label]
        self._block(info.node.body, info, dict(env), current, guard)
        self.active.remove(key)


def _scenario(contract: dict[str, object]) -> dict[str, object]:
    action = str(contract.get("action") or "__default__")
    args: dict[str, object] = {
        "__symbolic_payload__": True,
        "confirmed": contract.get("class") != "N",
    }
    if action != "__default__":
        args["action"] = action
    return {"args": args}


def _state(result: PathResult, declared: set[str]) -> str:
    mutations = {item["effect"] for item in result.compatible if item["operation"] not in {"READ", "OBSERVE"}}
    guarded_extra = {item["effect"] for item in result.guarded if item["operation"] not in {"READ", "OBSERVE"}} - declared
    if mutations - declared:
        return "CONFIRMED_UNDER_DECLARED"
    if result.unresolved:
        return "UNKNOWN"
    if guarded_extra:
        return "GUARDED_OR_SCENARIO_DEPENDENT"
    return "CONFIRMED"


def _dedupe(items: list[dict[str, object]]) -> list[dict[str, object]]:
    unique: dict[str, dict[str, object]] = {}
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        unique.setdefault(key, item)
    return list(unique.values())


def _evidence_bundle(items: list[dict[str, object]], limit: int = 64) -> dict[str, object]:
    canonical = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "total": len(items),
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "truncated": len(items) > limit,
        "items": items[:limit],
    }


def analyze_contracts() -> dict[str, object]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    rules = json.loads(V13_RULES_PATH.read_text(encoding="utf-8"))
    contracts = json.loads(CONTRACTS_PATH.read_text(encoding="utf-8"))["contracts"]
    index = ProjectIndex.backend()
    results: list[dict[str, object]] = []
    counts: dict[str, int] = {}
    for contract in contracts:
        entrypoint = index.tool_entrypoint(str(contract["tool"]))
        engine = PathAnalyzer(index, rules)
        if entrypoint:
            engine.walk(entrypoint, _scenario(contract))
        else:
            engine.result.unresolved.append({"reason": "tool_alias_not_found", "target": contract["tool"]})
        declared = set(rules["declared_surface_effects"][contract["surface_profile"]])
        engine.result.compatible = _dedupe(engine.result.compatible)
        engine.result.guarded = _dedupe(engine.result.guarded)
        engine.result.excluded = _dedupe(engine.result.excluded)
        engine.result.unresolved = _dedupe(engine.result.unresolved)
        state = _state(engine.result, declared)
        counts[state] = counts.get(state, 0) + 1
        results.append({
            "contract_id": contract["id"], "tool": contract["tool"], "action": contract["action"],
            "scenario": _scenario(contract), "declared_surface": contract["surface_profile"],
            "declared_effects": sorted(declared), "entrypoint": entrypoint, "state": state,
            "compatible_effects": _evidence_bundle(engine.result.compatible),
            "guarded_effects": _evidence_bundle(engine.result.guarded),
            "excluded_paths": _evidence_bundle(engine.result.excluded),
            "unresolved_paths": _evidence_bundle(engine.result.unresolved),
            "visited_functions": sorted(engine.result.visited),
        })
    return {
        "schema": "marvin.e7-direct-path-surface-analysis/1.0",
        "status": "published_without_tool_execution_or_contract_mutation",
        "tool_execution_performed": False, "contract_mutation_performed": False,
        "contracts": len(results), "counts": counts,
        "policy_sha256": sha256(POLICY_PATH), "rules_sha256": sha256(RULES_PATH),
        "v1_3_rules_sha256": sha256(V13_RULES_PATH), "v1_3_result_sha256": sha256(V13_RESULT_PATH),
        "analyzer_sha256": sha256(ROOT / "scripts" / "e7_path_surface_analyzer.py"),
        "contracts_sha256": sha256(CONTRACTS_PATH), "source_hashes": index.source_hashes,
        "results": results,
        "limitations": ["loops_and_exception_paths_are_conservative", "runtime_injected_callbacks_remain_unknown", "no_business_tool_was_executed"]
    }


def main() -> int:
    output = analyze_contracts()
    destination = BASE / "direct-path-surface-analysis.json"
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"E7 Path Surface Analysis - {output['contracts']} contracts | {output['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
