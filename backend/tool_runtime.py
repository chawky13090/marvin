"""Composition injectable du gateway commun pour tous les consommateurs d'outils."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable

import api_observability
import audit
import database as db
import engineering_runtime
import tool_gateway
import tools as tool_module
from config import (
    DEFAULT_PERMISSION_LEVEL,
    PERMISSION_EXPERT,
    PERMISSION_SECURE,
    PERMISSION_STANDARD,
)


_PERMISSION_LEVELS = frozenset(
    {PERMISSION_SECURE, PERMISSION_STANDARD, PERMISSION_EXPERT}
)


def current_permission_level(storage: Any | None = None) -> int:
    effective_storage = storage or db
    try:
        value = effective_storage.get_setting("permission_level")
        candidate = int(value) if value is not None else DEFAULT_PERMISSION_LEVEL
    except Exception:
        return DEFAULT_PERMISSION_LEVEL
    return candidate if candidate in _PERMISSION_LEVELS else DEFAULT_PERMISSION_LEVEL


async def execute(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    source: str,
    confirmed_by_ui: bool = False,
    conversation_id: str | None = None,
    request_id: str | None = None,
    idempotency_key: str | None = None,
    permission_level: int | None = None,
    registry: Mapping[str, Any] | None = None,
    specifications: Sequence[dict[str, Any]] | None = None,
    database: Any | None = None,
    normalizer: Callable[..., Any] | None = None,
    audit_logger: Callable[..., Any] | None = None,
    tool_call_id: str | None = None,
    execution_context: dict[str, Any] | None = None,
    canonicalized_from: str | None = None,
) -> tool_gateway.ToolGatewayResult:
    effective_database = database if database is not None else db
    try:
        effective_permission = (
            current_permission_level(effective_database)
            if permission_level is None
            else int(permission_level)
        )
    except (TypeError, ValueError):
        effective_permission = DEFAULT_PERMISSION_LEVEL
    if effective_permission not in _PERMISSION_LEVELS:
        effective_permission = DEFAULT_PERMISSION_LEVEL
    effective_source = str(source).strip()[:80] or "unknown"
    return await tool_gateway.execute_tool(
        tool_gateway.ToolGatewayRequest(
            tool_name=str(tool_name),
            arguments=dict(arguments),
            source=effective_source,
            permission_level=effective_permission,
            conversation_id=conversation_id,
            request_id=request_id or api_observability.current_request_id(),
            confirmed_by_ui=bool(confirmed_by_ui),
            idempotency_key=idempotency_key,
            tool_call_id=tool_call_id,
            execution_context=execution_context,
            canonicalized_from=canonicalized_from,
        ),
        registry=registry if registry is not None else tool_module.TOOLS_REGISTRY,
        specifications=(
            specifications if specifications is not None else tool_module.TOOLS_SPEC
        ),
        database=effective_database,
        normalizer=(
            normalizer
            if normalizer is not None
            else engineering_runtime.normalize_tool_result
        ),
        audit_logger=audit_logger if audit_logger is not None else audit.log_action,
    )
