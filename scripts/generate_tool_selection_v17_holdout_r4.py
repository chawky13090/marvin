"""Run the frozen v1.5 generator with bounded per-intent review batches.

This wrapper intentionally preserves authorship, oracle, novelty and selection semantics from
r3.  It only splits the two long review requests by software intent so one truncated response
cannot invalidate the full seven-family campaign.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "backend"))

import generate_tool_selection_v13_holdout as shared
import generate_tool_selection_v15_holdout_r3 as r3


BASE = ROOT / "benchmarks/tool-selection/v1.7"
POLICY = BASE / "holdout-generation-freeze-r4.json"
CORPUS = BASE / "holdout-corpus-r4.json"
ORACLE = BASE / "holdout-oracle-r4.json"
REPORT = BASE / "holdout-generation-report-r4.json"
DIAGNOSTIC = BASE / "holdout-generation-diagnostics-r4.json"


def _review_payload(prompt: str) -> tuple[str, list[dict[str, Any]]] | None:
    marker = "\nITEMS:\n"
    if marker not in prompt:
        return None
    prefix, encoded = prompt.split(marker, 1)
    rows = json.loads(encoded)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Lot de revue r4 invalide.")
    return prefix, rows


async def _bounded_reviews(
    model: str,
    system: str,
    user: str,
    *,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    parsed = _review_payload(user)
    if parsed is None or "révises sans corriger" not in system:
        return await _ORIGINAL_CHAT(model, system, user, seed=seed)

    prefix, rows = parsed
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        intent = str(row.get("intent") or "")
        if intent not in r3.INTENTS:
            raise ValueError("Intention absente ou inconnue dans la revue r4.")
        grouped[intent].append(row)
    if set(grouped) != set(r3.INTENTS):
        raise ValueError("La revue r4 doit couvrir exactement toutes les intentions gelées.")

    combined: list[dict[str, Any]] = []
    batches: list[dict[str, Any]] = []
    for offset, intent in enumerate(r3.INTENTS):
        batch = grouped[intent]
        response, metadata = await _ORIGINAL_CHAT(
            model,
            system,
            prefix + "\nITEMS:\n" + json.dumps(
                batch,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            seed=seed + offset,
        )
        items = response.get("items")
        if not isinstance(items, list):
            raise ValueError(f"Revue r4 sans items pour {intent}.")
        expected_ids = {str(row.get("id") or "") for row in batch}
        observed_ids = {
            str(row.get("id") or "")
            for row in items
            if isinstance(row, dict)
        }
        if observed_ids != expected_ids:
            raise ValueError(f"Revue r4 incomplète pour {intent}.")
        combined.extend(items)
        batches.append({
            "intent": intent,
            "count": len(batch),
            "metadata": metadata,
        })
    return {"items": combined}, {
        "requested_model": model,
        "review_batching": "one_request_per_intent",
        "batch_count": len(batches),
        "batches": batches,
    }


async def run() -> dict[str, Any]:
    for path in (CORPUS, ORACLE, REPORT, DIAGNOSTIC):
        if path.exists():
            raise RuntimeError(f"Campagne r4 déjà consommée : {path.name}")

    r3.POLICY = POLICY
    r3.CORPUS = CORPUS
    r3.ORACLE = ORACLE
    r3.REPORT = REPORT
    r3.DIAGNOSTIC = DIAGNOSTIC
    shared._chat = _bounded_reviews
    try:
        return await r3.run()
    finally:
        shared._chat = _ORIGINAL_CHAT


_ORIGINAL_CHAT = shared._chat


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result["counts"], ensure_ascii=False, separators=(",", ":")))
