"""Generate r6 with text-only reviewers and the frozen calculable terminal oracle.

The Cloud reviewers only decide whether a synthetic prompt expresses the declared intent and
one action. They never receive product results, tool names, catalog entries or terminal calls.
"""

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


BASE = ROOT / "benchmarks/tool-selection/v1.8"
POLICY = BASE / "holdout-generation-freeze-r6.json"
CORPUS = BASE / "holdout-corpus-r6.json"
ORACLE = BASE / "holdout-oracle-r6.json"
REPORT = BASE / "holdout-generation-report-r6.json"
DIAGNOSTIC = BASE / "holdout-generation-diagnostics-r6.json"

TEXT_REVIEW_SYSTEM = (
    "Tu révises uniquement le texte d'une demande synthétique, sans corriger ni proposer "
    "d'outil. JSON strict sans Markdown."
)
TEXT_REVIEW_RUBRIC = (
    "Retourne {items:[{id,valid}]}. valid=true seulement si le texte exprime exactement "
    "l'intention déclarée et une seule action. Refuse les demandes ambiguës, multi-actions, "
    "vides ou dont l'intention textuelle diffère. Ne juge ni faisabilité, ni sécurité, ni outil."
)


def _text_only_review_payload(user: str) -> str:
    marker = "\nITEMS:\n"
    if marker not in user:
        raise ValueError("Revue r6 sans lot ITEMS borné.")
    encoded = user.rsplit(marker, 1)[1]
    rows = json.loads(encoded)
    if not isinstance(rows, list) or not rows:
        raise ValueError("Lot de revue r6 vide ou invalide.")
    sanitized: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Item de revue r6 invalide.")
        identity = str(row.get("id") or "")
        intent = str(row.get("intent") or "")
        prompt = str(row.get("prompt") or "")
        if not identity or not intent or not prompt:
            raise ValueError("Item de revue r6 incomplet.")
        sanitized.append({"id": identity, "intent": intent, "prompt": prompt})
    payload = TEXT_REVIEW_RUBRIC + "\nITEMS:\n" + json.dumps(
        sanitized,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    forbidden = ("consensus_calls", "accepted_calls", "winget_", "TOOLS_SPEC", "CATALOGUE")
    if any(token in payload for token in forbidden):
        raise ValueError("La revue r6 expose une donnée interdite.")
    return payload


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
        clean_user = _text_only_review_payload(user)
        response, metadata = await _CLOUD_CHAT(
            model,
            TEXT_REVIEW_SYSTEM,
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
            raise RuntimeError(f"Campagne r6 déjà consommée : {path.name}")
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
