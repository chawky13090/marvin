"""Gèle les candidats de campagne B sans exécuter la moindre action."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Objet JSON attendu : {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _environment(tool: str) -> str:
    if tool.startswith("ssh_"):
        return "debian_test_vm"
    if tool.startswith(("email_", "billing_", "itsm_")):
        return "controlled_external_double"
    return "windows_test_vm"


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    inventory_path = BASE / "inventory.json"
    policy_path = BASE / "campaign-b-policy.json"
    inventory = _load(inventory_path)
    policy = _load(policy_path)
    if policy.get("execution_authorized") is not False:
        raise RuntimeError("La pré-inscription doit interdire l'exécution.")
    tool_execution_totals: dict[str, int] = {}
    for item in inventory.get("items", []):
        tool = str(item.get("tool") or "")
        tool_execution_totals[tool] = tool_execution_totals.get(tool, 0) + int(
            item.get("usage", {}).get("executions", 0)
        )
    candidates = []
    for item in inventory.get("items", []):
        tool_never_executed = tool_execution_totals.get(str(item["tool"]), 0) == 0
        if not item.get("llm_visible"):
            continue
        if not tool_never_executed and int(item.get("risk_tier", 0)) < 4:
            continue
        if item.get("evidence", {}).get("E4") or item.get("evidence", {}).get("E7"):
            continue
        executions = int(item.get("usage", {}).get("executions", 0))
        candidates.append(
            {
                "tool": item["tool"],
                "action": item["action"],
                "risk_tier": item["risk_tier"],
                "risk_basis": item["risk_basis"],
                "action_never_executed": executions == 0,
                "tool_never_executed": tool_never_executed,
                "historical_execution_count": executions,
                "human_message_count": int(
                    item.get("usage", {}).get("distinct_human_message_count", 0)
                ),
                "missing_evidence": [
                    level for level in item.get("missing_evidence", []) if level in {"E4", "E7"}
                ],
                "required_environment": _environment(str(item["tool"])),
                "execution_authorized": False,
            }
        )
    candidates.sort(
        key=lambda item: (
            not item["tool_never_executed"],
            not item["action_never_executed"],
            -int(item["risk_tier"]),
            str(item["tool"]),
            str(item["action"]),
        )
    )
    first_wave_tools = sorted(
        {item["tool"] for item in candidates if item["tool_never_executed"]}
    )
    payload = {
        "schema": "marvin.tool-evidence-campaign-b-candidates/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "frozen_candidates_execution_locked",
        "source_hashes": {
            inventory_path.relative_to(ROOT).as_posix(): _sha256(inventory_path),
            policy_path.relative_to(ROOT).as_posix(): _sha256(policy_path),
        },
        "summary": {
            "candidate_tool_action_pairs": len(candidates),
            "first_wave_never_executed_tools": len(first_wave_tools),
            "never_executed_actions_on_partially_exercised_tools": sum(
                item["action_never_executed"] and not item["tool_never_executed"]
                for item in candidates
            ),
            "execution_authorized": False,
        },
        "first_wave_tools": first_wave_tools,
        "candidates": candidates,
    }
    _write_atomic(BASE / "campaign-b-candidates.json", payload)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
