"""Routes de documentation des interventions techniques."""

from fastapi import APIRouter, HTTPException

import database as db


router = APIRouter(tags=["technical-docs"])


@router.get("/api/docs/interventions")
async def docs_interventions_list(
    client_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
):
    return {"interventions": db.doc_intervention_list(client_id, status, limit)}


@router.post("/api/docs/interventions")
async def docs_interventions_create(body: dict):
    if not body.get("title"):
        raise HTTPException(status_code=400, detail="Titre requis")
    return db.doc_intervention_create(body)


@router.get("/api/docs/interventions/{iid}")
async def docs_interventions_get(iid: str):
    intervention = db.doc_intervention_get(iid)
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    return intervention


@router.patch("/api/docs/interventions/{iid}")
async def docs_interventions_update(iid: str, body: dict):
    intervention = db.doc_intervention_update(iid, body)
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    return intervention


@router.delete("/api/docs/interventions/{iid}")
async def docs_interventions_delete(iid: str):
    db.doc_intervention_delete(iid)
    return {"success": True}


@router.get("/api/docs/documents")
async def docs_documents_list(
    intervention_id: str | None = None,
    client_id: str | None = None,
    doc_type: str | None = None,
):
    return {"documents": db.doc_document_list(intervention_id, client_id, doc_type)}


@router.delete("/api/docs/documents/{did}")
async def docs_documents_delete(did: str):
    db.doc_document_delete(did)
    return {"success": True}


@router.get("/api/docs/templates")
async def docs_templates_list(doc_type: str | None = None):
    return {"templates": db.doc_template_list(doc_type)}


@router.get("/api/docs/assets")
async def docs_assets_list(client_id: str | None = None):
    return {"assets": db.doc_asset_list(client_id)}


@router.post("/api/docs/assets")
async def docs_assets_create(body: dict):
    if not body.get("name"):
        raise HTTPException(status_code=400, detail="Nom requis")
    return db.doc_asset_create(body)


@router.delete("/api/docs/assets/{aid}")
async def docs_assets_delete(aid: str):
    db.doc_asset_delete(aid)
    return {"success": True}
