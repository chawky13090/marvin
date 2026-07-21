"""Registre append-only reliant les affirmations finales aux preuves disponibles."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import evidence_fabric
from config import DATA_DIR


LEDGER_PATH = Path(DATA_DIR) / "truth_ledger.jsonl"
_LOCK = threading.RLock()


def record_response(
    *,
    conversation_id: str,
    answer: str,
    citations: list[str],
    evidence_tools: list[str],
    reviewed: bool,
    sources: list[dict[str, Any]] | None = None,
    contradictions: list[str] | None = None,
) -> dict[str, Any]:
    if sources is None:
        sources = [{"url": url, "citation": str(index)} for index, url in enumerate(citations, start=1)]
    bundle = evidence_fabric.build_bundle(
        answer,
        sources=sources,
        evidence_tools=evidence_tools,
        reviewed=reviewed,
        contradictions=contradictions,
    )
    entries = []
    for claim in bundle["claims"]:
        entries.append({
            "id": uuid.uuid4().hex,
            **claim,
        })
    record = {
        "id": uuid.uuid4().hex,
        "conversation_id": conversation_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "claims": entries,
        "claim_count": len(entries),
        "sourced_count": sum(1 for item in entries if item["status"] == "sourced"),
        "unsupported_count": sum(1 for item in entries if item["status"] == "unsupported"),
        "epistemic_debt": bundle["epistemic_debt"],
        "source_firewall": bundle["source_firewall"],
        "source_catalog": bundle["source_catalog"],
        "contradictions": bundle["contradictions"],
    }
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, LEDGER_PATH.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def list_records(*, conversation_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    records = []
    with _LOCK:
        for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if conversation_id and record.get("conversation_id") != conversation_id:
                continue
            records.append(record)
    records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return records[: max(1, min(int(limit), 1000))]
