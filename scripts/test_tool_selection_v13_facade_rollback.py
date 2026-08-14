"""Vérifie que la façade rejetée n'est plus présente dans le produit."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from tools import TOOLS_SPEC


def main() -> None:
    assessment = json.loads(
        (ROOT / "benchmarks/tool-selection/v1.3/ab-assessment.json").read_text(encoding="utf-8")
    )
    agent_source = (ROOT / "backend/agent.py").read_text(encoding="utf-8")
    assert assessment["mechanical_verdict"]["rollback_required"] is True
    assert not (ROOT / "backend/tool_canonical_facade.py").exists()
    assert "tool_canonical_facade" not in agent_source
    assert "_build_canonical_tool_view" not in agent_source
    assert len(TOOLS_SPEC) == 364
    print("Tool selection v1.3 rollback OK - rejected facade absent, 364 tools preserved.")


if __name__ == "__main__":
    main()
