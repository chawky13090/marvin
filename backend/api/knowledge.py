"""API de lecture Memory Mesh et Truth Ledger."""
from fastapi import APIRouter, HTTPException, Query

import engineering_radar
import language_registry
import memory_mesh
import truth_ledger


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/memory-mesh")
async def memory_mesh_view(kind: str | None = Query(default=None, max_length=30)):
    return {"stats": memory_mesh.stats(), "memories": memory_mesh.list_metadata(kind=kind)}


@router.get("/truth-ledger")
async def truth_ledger_view(
    conversation_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
):
    integrity = truth_ledger.evidence_integrity()
    return {
        "records": (
            truth_ledger.list_records(conversation_id=conversation_id, limit=limit)
            if integrity["valid"]
            else []
        ),
        "evidence_integrity": integrity,
        "blocked_reason": None if integrity["valid"] else "truth_ledger_integrity_invalid",
    }


@router.get("/truth-ledger/integrity")
async def truth_ledger_integrity():
    return truth_ledger.evidence_integrity()


@router.get("/evidence-summary")
async def evidence_summary(limit: int = Query(default=200, ge=1, le=1000)):
    integrity = truth_ledger.evidence_integrity()
    records = truth_ledger.list_records(limit=limit) if integrity["valid"] else []
    claims = sum(int(item.get("claim_count") or 0) for item in records)
    sourced = sum(int(item.get("sourced_count") or 0) for item in records)
    unsupported = sum(int(item.get("unsupported_count") or 0) for item in records)
    debt_values = [
        float((item.get("epistemic_debt") or {}).get("score"))
        for item in records
        if (item.get("epistemic_debt") or {}).get("score") is not None
    ]
    return {
        "records": len(records),
        "claims": claims,
        "sourced_claims": sourced,
        "unsupported_claims": unsupported,
        "claim_coverage": round(sourced / claims, 4) if claims else None,
        "average_epistemic_debt": round(sum(debt_values) / len(debt_values), 4) if debt_values else None,
        "flagged_sources": sum(
            int((item.get("source_firewall") or {}).get("flagged_count") or 0)
            for item in records
        ),
        "evidence_integrity": integrity,
        "blocked_reason": None if integrity["valid"] else "truth_ledger_integrity_invalid",
    }


@router.get("/engineering-radar")
async def engineering_radar_view(
    language: str | None = Query(default=None, max_length=30),
):
    languages = [language_registry.normalize(language)] if language else list(language_registry.PROFILES)
    if language and languages[0] not in language_registry.PROFILES:
        raise HTTPException(status_code=422, detail="Langage inconnu dans la matrice Marvin.")
    result = engineering_radar.context(languages, max_chars=200_000)
    return {
        **{key: value for key, value in result.items() if key != "context"},
        "evidence_integrity": engineering_radar.evidence_integrity(),
    }


@router.get("/engineering-radar/integrity")
async def engineering_radar_integrity():
    return engineering_radar.evidence_integrity()


@router.post("/engineering-radar/refresh")
async def engineering_radar_refresh(
    language: str | None = Query(default=None, max_length=30),
):
    languages = [language_registry.normalize(language)] if language else None
    if languages and languages[0] not in language_registry.PROFILES:
        raise HTTPException(status_code=422, detail="Langage inconnu dans la matrice Marvin.")
    result = await engineering_radar.refresh(languages)
    return {**result, "evidence_integrity": engineering_radar.evidence_integrity()}
