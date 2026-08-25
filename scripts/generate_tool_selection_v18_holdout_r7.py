"""Generate r7 after a full offline rehearsal of the inherited selection pipeline."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import generate_tool_selection_v13_holdout as shared
import generate_tool_selection_v17_holdout_r4 as r4
import generate_tool_selection_v18_holdout_r5 as r5
import generate_tool_selection_v18_holdout_r6 as r6


BASE = ROOT / "benchmarks/tool-selection/v1.8"
POLICY = BASE / "holdout-generation-freeze-r7.json"
CORPUS = BASE / "holdout-corpus-r7.json"
ORACLE = BASE / "holdout-oracle-r7.json"
REPORT = BASE / "holdout-generation-report-r7.json"
DIAGNOSTIC = BASE / "holdout-generation-diagnostics-r7.json"


async def _contract_or_cloud_chat(
    model: str,
    system: str,
    user: str,
    *,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if "oracle fonctionnel indépendant" in system:
        return await r5._contract_or_cloud_chat(model, system, user, seed=seed)
    if "révises sans corriger" in system:
        clean_user = r6._text_only_review_payload(user)
        response, metadata = await _CLOUD_CHAT(
            model,
            r6.TEXT_REVIEW_SYSTEM,
            clean_user,
            seed=seed,
        )
        return response, {
            **metadata,
            "review_scope": "text_intent_and_single_action_only",
            "product_result_visible": False,
            "tool_name_visible": False,
            "terminal_call_visible": False,
        }
    return await _CLOUD_CHAT(model, system, user, seed=seed)


async def run() -> dict[str, Any]:
    for path in (CORPUS, ORACLE, REPORT, DIAGNOSTIC):
        if path.exists():
            raise RuntimeError(f"Campagne r7 déjà consommée : {path.name}")
    r4.POLICY = POLICY
    r4.CORPUS = CORPUS
    r4.ORACLE = ORACLE
    r4.REPORT = REPORT
    r4.DIAGNOSTIC = DIAGNOSTIC
    original = r4._ORIGINAL_CHAT
    r4._ORIGINAL_CHAT = _contract_or_cloud_chat
    try:
        return await r4.run()
    finally:
        r4._ORIGINAL_CHAT = original


_CLOUD_CHAT = shared._chat


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result["counts"], ensure_ascii=False, separators=(",", ":")))
