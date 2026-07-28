"""Registre append-only reliant les affirmations finales aux preuves disponibles."""
from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import evidence_fabric
from config import DATA_DIR
from durable_evidence_store import DurableEvidenceStore


LEDGER_PATH = Path(DATA_DIR) / "truth_ledger.jsonl"
MAX_ANSWER_CHARS = 200_000
MAX_SOURCES = 100
MAX_SOURCE_TEXT_CHARS = 20_000
MAX_CITATIONS = 100
MAX_EVIDENCE_TOOLS = 100
MAX_CONTRADICTIONS = 50
_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
_RECORD_ID = re.compile(r"^[0-9a-f]{32}$")


def _store() -> DurableEvidenceStore:
    return DurableEvidenceStore(
        LEDGER_PATH,
        stream_name="marvin.truth_ledger.responses",
        record_validator=_validate_record,
    )


def evidence_integrity() -> dict[str, Any]:
    return _store().verify()


def _public_reference_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if len(url) > 8_192:
        raise ValueError("Une URL de preuve est limitée à 8192 caractères.")
    try:
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("URL de preuve invalide.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in {80, 443}
    ):
        raise ValueError(
            "Une URL de preuve doit être HTTP(S), sans identifiants et sur un port standard."
        )
    return url


def _bounded_sources(sources: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if sources is None:
        return []
    if not isinstance(sources, list):
        raise TypeError("Les sources doivent être une liste.")
    if len(sources) > MAX_SOURCES:
        raise ValueError(f"Le Truth Ledger accepte au plus {MAX_SOURCES} sources.")
    projected: list[dict[str, Any]] = []
    for raw in sources:
        if not isinstance(raw, dict):
            raise TypeError("Chaque source doit être un objet.")
        aliases = raw.get("citations") or []
        if not isinstance(aliases, list):
            raise TypeError("Les alias de citation doivent être une liste.")
        projected.append({
            "citation": re.sub(
                r"[^A-Za-z0-9_-]+",
                "_",
                str(raw.get("citation") or raw.get("id") or ""),
            )[:80],
            "citations": [
                re.sub(r"[^A-Za-z0-9_-]+", "_", str(item))[:80]
                for item in aliases[:20]
            ],
            "title": str(raw.get("title") or "")[:300],
            "url": _public_reference_url(raw.get("url")),
            "text": str(
                raw.get("text") or raw.get("excerpt") or raw.get("snippet") or ""
            )[:MAX_SOURCE_TEXT_CHARS],
            "published_at": str(raw.get("published_at") or "")[:80],
            "retrieved_at": str(raw.get("retrieved_at") or "")[:80],
        })
    return projected


def _bounded_integer(value: Any, *, maximum: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f"Champ Truth Ledger invalide : {field}.")
    return value


def _validate_record(record: dict[str, Any]) -> None:
    """Valide aussi les lignes historiques non signées avant lecture ou extension."""
    if not isinstance(record, dict) or not _RECORD_ID.fullmatch(str(record.get("id") or "")):
        raise ValueError("Identité de preuve Truth Ledger invalide.")
    if not _CONVERSATION_ID.fullmatch(str(record.get("conversation_id") or "")):
        raise ValueError("Conversation de preuve Truth Ledger invalide.")
    created_at = str(record.get("created_at") or "")
    if not created_at or len(created_at) > 80:
        raise ValueError("Horodatage Truth Ledger invalide.")
    claims = record.get("claims")
    if not isinstance(claims, list) or len(claims) > 100:
        raise ValueError("Liste d'affirmations Truth Ledger invalide.")
    for claim in claims:
        if not isinstance(claim, dict) or not _RECORD_ID.fullmatch(
            str(claim.get("id") or "")
        ):
            raise ValueError("Affirmation Truth Ledger invalide.")
        if not 1 <= len(str(claim.get("claim") or "")) <= 1500:
            raise ValueError("Texte d'affirmation Truth Ledger invalide.")
        if claim.get("status") not in {"sourced", "tool_supported", "unsupported"}:
            raise ValueError("Statut d'affirmation Truth Ledger invalide.")
        for key in ("sources", "source_ids", "evidence_tools"):
            values = claim.get(key, [])
            if not isinstance(values, list) or len(values) > 100:
                raise ValueError(f"Champ d'affirmation invalide : {key}.")
        for url in claim.get("sources", []):
            _public_reference_url(url)
        for key in ("confidence", "debt", "lexical_support"):
            if key not in claim:
                continue
            value = claim[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0 <= float(value) <= 1
            ):
                raise ValueError(f"Score d'affirmation invalide : {key}.")
    claim_count = _bounded_integer(
        record.get("claim_count"),
        maximum=100,
        field="claim_count",
    )
    if claim_count != len(claims):
        raise ValueError("Le nombre d'affirmations ne correspond pas au contenu.")
    for key in ("sourced_count", "unsupported_count"):
        _bounded_integer(record.get(key), maximum=claim_count, field=key)
    source_catalog = record.get("source_catalog", [])
    if not isinstance(source_catalog, list) or len(source_catalog) > MAX_SOURCES:
        raise ValueError("Catalogue de sources Truth Ledger invalide.")
    for source in source_catalog:
        if not isinstance(source, dict):
            raise ValueError("Source Truth Ledger invalide.")
        _public_reference_url(source.get("url"))
    contradictions = record.get("contradictions", [])
    if not isinstance(contradictions, list) or len(contradictions) > MAX_CONTRADICTIONS:
        raise ValueError("Contradictions Truth Ledger invalides.")
    debt = record.get("epistemic_debt")
    if debt is not None:
        score = debt.get("score") if isinstance(debt, dict) else None
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 1
        ):
            raise ValueError("Dette épistémique Truth Ledger invalide.")


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
    if not isinstance(conversation_id, str) or not _CONVERSATION_ID.fullmatch(
        conversation_id
    ):
        raise ValueError("Identifiant de conversation Truth Ledger invalide.")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Une réponse non vide est requise.")
    if len(answer) > MAX_ANSWER_CHARS:
        raise ValueError(
            f"Une réponse Truth Ledger est limitée à {MAX_ANSWER_CHARS} caractères."
        )
    if not isinstance(citations, list) or len(citations) > MAX_CITATIONS:
        raise ValueError(f"Le Truth Ledger accepte au plus {MAX_CITATIONS} citations.")
    clean_citations = [
        normalized
        for item in citations
        if (normalized := _public_reference_url(item))
    ]
    if not isinstance(evidence_tools, list) or len(evidence_tools) > MAX_EVIDENCE_TOOLS:
        raise ValueError(
            f"Le Truth Ledger accepte au plus {MAX_EVIDENCE_TOOLS} outils de preuve."
        )
    clean_tools = []
    for item in evidence_tools:
        normalized = str(item or "").strip()
        if normalized and not _TOOL_NAME.fullmatch(normalized):
            raise ValueError("Nom d'outil de preuve invalide.")
        if normalized:
            clean_tools.append(normalized)
    if contradictions is not None and (
        not isinstance(contradictions, list)
        or len(contradictions) > MAX_CONTRADICTIONS
    ):
        raise ValueError(
            f"Le Truth Ledger accepte au plus {MAX_CONTRADICTIONS} contradictions."
        )
    clean_contradictions = [
        str(item)[:1000] for item in (contradictions or []) if str(item).strip()
    ]
    if sources is None:
        sources = [
            {"url": url, "citation": str(index)}
            for index, url in enumerate(clean_citations, start=1)
        ]
    else:
        sources = _bounded_sources(sources)
    bundle = evidence_fabric.build_bundle(
        answer,
        sources=sources,
        evidence_tools=clean_tools,
        reviewed=reviewed,
        contradictions=clean_contradictions,
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
    return _store().append(record)


def list_records(*, conversation_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if conversation_id is not None and (
        not isinstance(conversation_id, str)
        or not _CONVERSATION_ID.fullmatch(conversation_id)
    ):
        raise ValueError("Identifiant de conversation Truth Ledger invalide.")
    return _store().recent_verified(
        max(1, min(int(limit), 1000)),
        predicate=(
            (lambda record: record.get("conversation_id") == conversation_id)
            if conversation_id
            else None
        ),
    )
