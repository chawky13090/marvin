"""Inventaire déterministe des contrats OpenAPI de Marvin."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
MUTATION_METHODS = {"post", "put", "patch", "delete"}


def _family(path: str) -> str:
    parts = [part for part in path.split("/") if part and not part.startswith("{")]
    if not parts:
        return "root"
    if parts[0] == "api" and len(parts) > 1:
        return parts[1]
    return parts[0]


def _has_explicit_schema(operation: dict[str, Any]) -> bool:
    for response in operation.get("responses", {}).values():
        for content in response.get("content", {}).values():
            schema = content.get("schema")
            if isinstance(schema, dict) and schema:
                return True
    return False


def _has_error_contract(operation: dict[str, Any]) -> bool:
    return any(
        str(status).startswith(("4", "5")) and str(status) != "422"
        for status in operation.get("responses", {})
    )


def _has_idempotency_key(operation: dict[str, Any]) -> bool:
    return any(
        str(parameter.get("in")) == "header"
        and str(parameter.get("name", "")).casefold() == "idempotency-key"
        for parameter in operation.get("parameters", [])
        if isinstance(parameter, dict)
    )


def inventory(schema: dict[str, Any]) -> dict[str, Any]:
    operations: list[tuple[str, str, dict[str, Any]]] = []
    duplicates: list[str] = []
    seen: set[tuple[str, str]] = set()
    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            key = (path, method)
            if key in seen:
                duplicates.append(f"{method.upper()} {path}")
            seen.add(key)
            operations.append((path, method, operation))

    operation_ids = [
        str(operation.get("operationId") or "")
        for _path, _method, operation in operations
    ]
    duplicate_ids = sorted(
        key for key, count in Counter(operation_ids).items() if key and count > 1
    )
    family_rows: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "operations": 0,
            "mutations": 0,
            "typed_responses": 0,
            "documented_errors": 0,
            "secured": 0,
            "idempotent_mutations": 0,
        }
    )
    for path, method, operation in operations:
        row = family_rows[_family(path)]
        row["operations"] += 1
        if method in MUTATION_METHODS:
            row["mutations"] += 1
            row["idempotent_mutations"] += int(_has_idempotency_key(operation))
        row["typed_responses"] += int(_has_explicit_schema(operation))
        row["documented_errors"] += int(_has_error_contract(operation))
        row["secured"] += int(bool(operation.get("security")))

    mutations = [
        operation
        for _path, method, operation in operations
        if method in MUTATION_METHODS
    ]
    return {
        "openapi": str(schema.get("openapi") or ""),
        "version": str(schema.get("info", {}).get("version") or ""),
        "paths": len(schema.get("paths", {})),
        "operations": len(operations),
        "mutations": len(mutations),
        "typed_responses": sum(
            _has_explicit_schema(operation) for _path, _method, operation in operations
        ),
        "documented_errors": sum(
            _has_error_contract(operation) for _path, _method, operation in operations
        ),
        "secured": sum(
            bool(operation.get("security"))
            for _path, _method, operation in operations
        ),
        "idempotent_mutations": sum(
            _has_idempotency_key(operation) for operation in mutations
        ),
        "request_bodies": sum("requestBody" in operation for operation in mutations),
        "untagged": sum(not operation.get("tags") for _p, _m, operation in operations),
        "missing_operation_ids": operation_ids.count(""),
        "duplicate_operations": duplicates,
        "duplicate_operation_ids": duplicate_ids,
        "families": dict(sorted(family_rows.items())),
    }
