"""Historique serveur borne pour le chat et la consultation UI."""

from __future__ import annotations

import json
from typing import Any

from agent_tool_step import compact_tool_result


MODEL_HISTORY_MAX_BYTES = 512 * 1024
UI_HISTORY_MAX_BYTES = 768 * 1024
UI_TOOL_PROJECTION_MAX_BYTES = 24 * 1024
UI_TEXT_PROJECTION_MAX_BYTES = 64 * 1024


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _project_result(result: Any, tool_name: str, max_bytes: int = UI_TOOL_PROJECTION_MAX_BYTES) -> tuple[Any, bool]:
    if _size(result) <= max_bytes:
        return result, False
    projected = compact_tool_result(result, tool_name=tool_name)
    if len(projected.encode("utf-8")) > max_bytes:
        projected = projected[: max_bytes // 2]
    return {
        "_marvin_projection": True,
        "projection_truncated": True,
        "summary": projected,
        "detail_available": True,
    }, True


def _ui_message(message: dict[str, Any]) -> tuple[dict[str, Any], int]:
    item = dict(message)
    detail_count = 0
    if item.get("role") == "tool" and isinstance(item.get("tool_results"), list):
        projected_results = []
        for receipt in item["tool_results"]:
            receipt = dict(receipt) if isinstance(receipt, dict) else {"result": receipt}
            result, truncated = _project_result(
                receipt.get("result"), str(receipt.get("toolName") or "")
            )
            receipt["result"] = result
            if truncated:
                receipt["detail_message_id"] = item.get("id")
                detail_count += 1
            projected_results.append(receipt)
        item["tool_results"] = projected_results
        item["content"] = ""
    elif isinstance(item.get("content"), str) and len(item["content"].encode("utf-8")) > UI_TEXT_PROJECTION_MAX_BYTES:
        original_bytes = len(item["content"].encode("utf-8"))
        item["content"] = item["content"][: UI_TEXT_PROJECTION_MAX_BYTES // 2]
        item["content_projection"] = {
            "truncated": True,
            "original_bytes": original_bytes,
        }
    return item, detail_count


def ui_page(messages: list[dict], *, max_bytes: int = UI_HISTORY_MAX_BYTES) -> dict[str, Any]:
    """Retourne un suffixe chronologique contigu, sans trou sous la borne d'octets."""
    groups: list[list[dict[str, Any]]] = []
    for message in messages:
        if (
            message.get("role") == "tool"
            and groups
            and groups[-1][0].get("role") == "assistant"
        ):
            groups[-1].append(message)
        else:
            groups.append([message])
    selected_groups_reversed: list[list[dict[str, Any]]] = []
    used = 0
    details_available = 0
    selected_count = 0
    for group in reversed(groups):
        projected_group: list[dict[str, Any]] = []
        group_details = 0
        for message in group:
            item, item_details = _ui_message(message)
            projected_group.append(item)
            group_details += item_details
        group_size = _size(projected_group)
        if selected_groups_reversed and used + group_size > max_bytes:
            break
        if not selected_groups_reversed and group_size > max_bytes:
            raise ValueError("Un groupe de messages projeté dépasse le budget UI global.")
        selected_groups_reversed.append(projected_group)
        selected_count += len(projected_group)
        details_available += group_details
        used += group_size
    selected = [
        item
        for group in reversed(selected_groups_reversed)
        for item in group
    ]
    deferred = len(messages) - selected_count
    return {
        "messages": selected,
        "used_bytes": used,
        "deferred_messages": deferred,
        "details_available": details_available,
        "next_before_rowid": (
            int(selected[0].get("_message_rowid") or 0) if selected else None
        ),
    }


def model_history(messages: list[dict], incoming: list[dict], *, max_bytes: int = MODEL_HISTORY_MAX_BYTES) -> tuple[list[dict], dict[str, Any]]:
    """Reconstruit un contexte récent, en retirant d'abord les reçus techniques anciens."""
    candidates: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "tool":
            content = message.get("content") or ""
            if len(str(content).encode("utf-8")) > 24 * 1024:
                content = json.dumps({"_marvin_projection": True, "summary": "Résultat technique ancien omis du contexte actif."}, ensure_ascii=False)
            candidates.append({"role": "tool", "content": content})
        elif role in {"user", "assistant"}:
            candidates.append({
                "role": role,
                "content": message.get("content") or "",
                **({"tool_calls": message.get("tool_calls")} if message.get("tool_calls") else {}),
            })
    selected: list[dict] = list(incoming)
    used = _size(selected)
    omitted = 0
    for item in reversed(candidates):
        item_size = _size(item)
        if used + item_size > max_bytes:
            omitted += 1
            continue
        selected.insert(0, item)
        used += item_size
    return selected, {
        "source": "sqlite_authoritative",
        "budget_bytes": max_bytes,
        "selected_bytes": used,
        "selected_messages": len(selected),
        "omitted_messages": omitted,
        "truncation_visible": omitted > 0,
    }
