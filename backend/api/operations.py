"""Routes de suivi des opérations, validations de commandes et santé client."""

from fastapi import APIRouter, HTTPException

import database as db


router = APIRouter(tags=["operations"])


@router.get("/api/ops/checks")
async def ops_checks_list(intervention_id: str | None = None, check_type: str | None = None):
    return {"checks": db.ops_check_list(intervention_id, check_type)}


@router.get("/api/ops/checks/{cid}")
async def ops_checks_get(cid: str):
    check = db.ops_check_get(cid)
    if not check:
        raise HTTPException(status_code=404, detail="Checklist introuvable")
    return check


@router.delete("/api/ops/checks/{cid}")
async def ops_checks_delete(cid: str):
    db.ops_check_delete(cid)
    return {"success": True}


@router.get("/api/ops/evidence")
async def ops_evidence_list_route(intervention_id: str | None = None, check_id: str | None = None):
    return {"evidence": db.ops_evidence_list(intervention_id, check_id)}


@router.get("/api/cmd/reviews")
async def cmd_reviews_list(
    intervention_id: str | None = None,
    risk_level: str | None = None,
    limit: int = 100,
):
    return {"reviews": db.cmd_review_list(intervention_id, risk_level, limit)}


@router.get("/api/cmd/rules")
async def cmd_rules_list_route():
    return {"rules": db.cmd_rules_list()}


@router.get("/api/cmd/approvals")
async def cmd_approvals_list(status: str | None = None):
    return {"approvals": db.approval_list(status)}


@router.post("/api/cmd/approvals/{aid}/decide")
async def cmd_approval_decide(aid: str, body: dict):
    decision = body.get("status", "approved")
    if decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="status doit être 'approved' ou 'rejected'")
    result = db.approval_decide(
        aid,
        decision,
        body.get("approver", ""),
        body.get("reason", ""),
    )
    if not result:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    return result


@router.get("/api/client-health/{client_id}")
async def client_health_get_route(client_id: str):
    return {"score": db.health_score_latest(client_id)}


@router.get("/api/client-health/{client_id}/history")
async def client_health_history_route(client_id: str, limit: int = 12):
    return {"history": db.health_score_history(client_id, limit)}


@router.get("/api/client-health/{client_id}/recommendations")
async def client_health_recos_route(client_id: str, status: str | None = None):
    return {"recommendations": db.health_recommendations_list(client_id, status)}
