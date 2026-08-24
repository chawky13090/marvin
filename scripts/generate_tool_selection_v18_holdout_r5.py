"""Generate r5 with Cloud authors/reviewers and the frozen calculable terminal oracle."""

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
import software_terminal_oracle_v1 as terminal_oracle


BASE = ROOT / "benchmarks/tool-selection/v1.8"
POLICY = BASE / "holdout-generation-freeze-r5.json"
ORACLE_POLICY = BASE / "software-terminal-oracle-preregistration.json"
CORPUS = BASE / "holdout-corpus-r5.json"
ORACLE = BASE / "holdout-oracle-r5.json"
REPORT = BASE / "holdout-generation-report-r5.json"
DIAGNOSTIC = BASE / "holdout-generation-diagnostics-r5.json"


def _requests_from_oracle_prompt(prompt: str) -> list[dict[str, Any]]:
    marker = "\nDEMANDES:\n"
    if marker not in prompt:
        raise ValueError("Prompt oracle r5 sans demandes bornées.")
    rows = json.loads(prompt.rsplit(marker, 1)[1])
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Demandes oracle r5 invalides.")
    return rows


def _deterministic_oracle_response(prompt: str) -> dict[str, Any]:
    policy = json.loads(ORACLE_POLICY.read_text(encoding="utf-8"))
    contracts = policy["intent_contracts"]
    items = []
    for row in _requests_from_oracle_prompt(prompt):
        calls = terminal_oracle.accepted_calls_for_reviewed_item(
            row,
            contracts,
            reviewer_a_valid=True,
            reviewer_b_valid=True,
        )
        items.append({"id": str(row.get("id") or ""), "accepted_calls": calls})
    return {"items": items}


async def _contract_or_cloud_chat(
    model: str,
    system: str,
    user: str,
    *,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if "oracle fonctionnel indépendant" in system:
        response = _deterministic_oracle_response(user)
        return response, {
            "requested_model": None,
            "observed_model": None,
            "execution": "calculable_terminal_oracle_v1",
            "contract": str(ORACLE_POLICY.relative_to(ROOT)).replace("\\", "/"),
            "item_count": len(response["items"]),
            "cloud_call": False,
        }
    return await _CLOUD_CHAT(model, system, user, seed=seed)


async def run() -> dict[str, Any]:
    for path in (CORPUS, ORACLE, REPORT, DIAGNOSTIC):
        if path.exists():
            raise RuntimeError(f"Campagne r5 déjà consommée : {path.name}")
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
