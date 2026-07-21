"""Routes de gestion des clients, devis et catalogue de facturation."""

from fastapi import APIRouter, HTTPException

import database as db


router = APIRouter(tags=["billing"])


@router.get("/api/billing/clients")
async def billing_clients_list(client_type: str | None = None):
    return {"clients": db.billing_client_list(client_type)}


@router.post("/api/billing/clients")
async def billing_clients_create(body: dict):
    if not body.get("name"):
        raise HTTPException(status_code=400, detail="Nom requis")
    return db.billing_client_create(body)


@router.get("/api/billing/clients/{cid}")
async def billing_clients_get(cid: str):
    client = db.billing_client_get(cid)
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return client


@router.patch("/api/billing/clients/{cid}")
async def billing_clients_update(cid: str, body: dict):
    client = db.billing_client_update(cid, body)
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return client


@router.delete("/api/billing/clients/{cid}")
async def billing_clients_delete(cid: str):
    db.billing_client_delete(cid)
    return {"success": True}


@router.get("/api/billing/quotes")
async def billing_quotes_list(client_id: str | None = None, status: str | None = None):
    return {"quotes": db.billing_quote_list(client_id, status)}


@router.post("/api/billing/quotes")
async def billing_quotes_create(body: dict):
    if not body.get("client_id"):
        raise HTTPException(status_code=400, detail="client_id requis")
    return db.billing_quote_create(body)


@router.get("/api/billing/quotes/{qid}")
async def billing_quotes_get(qid: str):
    quote = db.billing_quote_get(qid)
    if not quote:
        raise HTTPException(status_code=404, detail="Devis introuvable")
    return quote


@router.patch("/api/billing/quotes/{qid}")
async def billing_quotes_update(qid: str, body: dict):
    quote = db.billing_quote_update(qid, body)
    if not quote:
        raise HTTPException(status_code=404, detail="Devis introuvable")
    return quote


@router.delete("/api/billing/quotes/{qid}")
async def billing_quotes_delete(qid: str):
    db.billing_quote_delete(qid)
    return {"success": True}


@router.get("/api/billing/catalog")
async def billing_catalog_get(category: str | None = None):
    return {"services": db.billing_catalog_list(category)}


@router.post("/api/billing/catalog")
async def billing_catalog_add(body: dict):
    if not body.get("name"):
        raise HTTPException(status_code=400, detail="Nom requis")
    return db.billing_catalog_create(body)


@router.delete("/api/billing/catalog/{sid}")
async def billing_catalog_remove(sid: str):
    db.billing_catalog_delete(sid)
    return {"success": True}
