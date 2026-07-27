"""Régressions déterministes des contrôles opérationnels pré/post-intervention."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import operations_safety


async def _run() -> None:
    writes: list[tuple] = []
    original_get = operations_safety.db.ops_check_get
    original_set = operations_safety.db.ops_result_set
    try:
        operations_safety.db.ops_check_get = lambda _check_id: {
            "id": "check-1",
            "check_type": "postcheck",
            "status": "pending",
            "items": [],
        }
        operations_safety.db.ops_result_set = lambda *args: writes.append(args)

        assert "check_type" in (
            await operations_safety.execute_ops_checklist_generate(
                {"check_type": "inconnu"}
            )
        )["error"]
        generated = await operations_safety.execute_ops_checklist_generate(
            {"intervention_type": "deployment", "check_type": "precheck"}
        )
        assert generated["success"] is True
        assert generated["count"] >= 4

        mismatch = await operations_safety.execute_ops_precheck_run(
            {"check_id": "check-1", "results": []}
        )
        assert "incompatible" in mismatch["error"]
        assert writes == []
        assert "liste attendue" in (
            await operations_safety.execute_ops_postcheck_run(
                {"check_id": "check-1", "results": "ok"}
            )
        )["error"]
        assert "limité" in (
            await operations_safety.execute_ops_postcheck_run(
                {"check_id": "check-1", "results": [{}] * 101}
            )
        )["error"]
        assert "content" in (
            await operations_safety.execute_ops_evidence_add({"content": 42})
        )["error"]
        assert "Formats acceptés" in (
            await operations_safety.execute_ops_validation_report_generate(
                {"intervention_id": "iv-1", "format": "html"}
            )
        )["error"]

        public_names = [
            name.removeprefix("execute_")
            for name in dir(operations_safety)
            if name.startswith("execute_ops_")
        ]
        assert len(public_names) == 6
        for public_name in public_names:
            implementation = getattr(operations_safety, f"execute_{public_name}")
            assert getattr(tools, f"execute_{public_name}") is implementation
            assert tools.TOOLS_REGISTRY[public_name] is implementation
    finally:
        operations_safety.db.ops_check_get = original_get
        operations_safety.db.ops_result_set = original_set


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine contrôles opérationnels OK")
