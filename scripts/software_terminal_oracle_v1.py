"""Pure terminal-call oracle for independently reviewed software intent labels.

The module deliberately imports no Marvin product module and performs no I/O.  The caller
provides the frozen contract mapping; this code only validates and projects it.
"""

from __future__ import annotations

from typing import Any


def accepted_calls_for_reviewed_item(
    item: dict[str, Any],
    contracts: dict[str, Any],
    *,
    reviewer_a_valid: bool,
    reviewer_b_valid: bool,
) -> list[dict[str, Any]]:
    """Return terminal calls only when two reviewers confirm the declared intent."""

    if not reviewer_a_valid or not reviewer_b_valid:
        return []
    intent = str(item.get("intent") or "")
    contract = contracts.get(intent)
    if not isinstance(contract, dict):
        return []
    calls = contract.get("accepted_terminal_calls")
    if not isinstance(calls, list) or not calls:
        return []
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for call in calls:
        if not isinstance(call, dict):
            return []
        tool = str(call.get("tool") or "")
        action_value = call.get("action")
        action = str(action_value) if action_value is not None else None
        if not tool:
            return []
        key = (tool, action)
        if key in seen:
            return []
        seen.add(key)
        normalized.append({"tool": tool, "action": action, "constraints": []})
    return normalized
