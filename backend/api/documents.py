"""Routes de génération, stockage et recherche documentaire RAG."""

import os

from fastapi import APIRouter, Body, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import database as db
import tools as tool_module


router = APIRouter(tags=["documents"])
_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(tool_module.__file__), "..", "data"))


@router.get("/api/documents")
async def list_documents():
    return await tool_module.TOOLS_REGISTRY["document_list"]({})


@router.get("/api/documents/templates")
async def document_templates():
    return {"templates": tool_module._doc_templates_list()}


@router.post("/api/documents/generate")
async def generate_document(body: dict = Body(...)):
    result = await tool_module.TOOLS_REGISTRY["document_generate"](body)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/api/documents/download")
async def download_document(path: str):
    base = os.path.join(_DATA_DIR, "documents_generes")
    target = os.path.abspath(path)
    if not target.startswith(base) or not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return FileResponse(
        target,
        filename=os.path.basename(target),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.get("/api/documents/letterhead")
async def get_letterhead():
    letterhead = db.get_setting("doc_letterhead")
    return letterhead if isinstance(letterhead, dict) else {}


@router.post("/api/documents/letterhead")
async def save_letterhead(body: dict = Body(...)):
    db.set_setting("doc_letterhead", body)
    return {"success": True}


@router.post("/api/documents/logo")
async def upload_logo(file: UploadFile = File(...)):
    documents_dir = os.path.join(_DATA_DIR, "documents_generes")
    os.makedirs(documents_dir, exist_ok=True)
    extension = (os.path.splitext(file.filename or "logo.png")[1] or ".png").lower()
    destination = os.path.join(documents_dir, "letterhead_logo" + extension)
    with open(destination, "wb") as output:
        output.write(await file.read())
    letterhead = db.get_setting("doc_letterhead")
    letterhead = letterhead if isinstance(letterhead, dict) else {}
    letterhead["logo"] = destination
    db.set_setting("doc_letterhead", letterhead)
    return {"success": True, "logo": destination}


class DocIndexBody(BaseModel):
    path: str


@router.post("/api/documents/index")
async def index_document(body: DocIndexBody):
    result = await tool_module.TOOLS_REGISTRY["document_index"]({"path": body.path})
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


class DocAskBody(BaseModel):
    question: str
    k: int = 6


@router.post("/api/documents/ask")
async def ask_documents(body: DocAskBody):
    result = await tool_module.TOOLS_REGISTRY["document_ask"](
        {"question": body.question, "k": body.k}
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


class DocRefineBody(BaseModel):
    file: str
    section: str
    instruction: str = ""
    notes: str = ""


@router.post("/api/documents/refine")
async def refine_document(body: DocRefineBody):
    result = await tool_module.TOOLS_REGISTRY["document_refine_section"](body.model_dump())
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/api/documents/{doc_id}")
async def forget_document(doc_id: str):
    return await tool_module.TOOLS_REGISTRY["document_forget"]({"id": doc_id})


@router.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    documents_dir = os.path.join(_DATA_DIR, "documents")
    os.makedirs(documents_dir, exist_ok=True)
    destination = os.path.join(documents_dir, os.path.basename(file.filename or "document"))
    with open(destination, "wb") as output:
        output.write(await file.read())
    result = await tool_module.TOOLS_REGISTRY["document_index"]({"path": destination})
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result
