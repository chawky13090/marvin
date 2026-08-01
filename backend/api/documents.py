"""Routes de génération, stockage et recherche documentaire RAG."""

import os

from fastapi import APIRouter, Body, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import database as db
import tool_runtime
import tools as tool_module
from storage_layout import roots
import libreoffice_runtime
import document_canvas


router = APIRouter(tags=["documents"])
_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(tool_module.__file__), "..", "data"))


def _documents_dir() -> str:
    return str(roots()[1] / "documents")


async def _document_tool(name: str, arguments: dict, *, confirmed_by_ui: bool = False):
    return (
        await tool_runtime.execute(
            name,
            arguments,
            source="documents_ui",
            confirmed_by_ui=confirmed_by_ui,
        )
    ).result


@router.get("/api/documents")
async def list_documents():
    return await _document_tool("document_list", {})


@router.get("/api/documents/templates")
async def document_templates():
    return {"templates": tool_module._doc_templates_list()}


@router.get("/api/documents/runtime")
async def document_runtime():
    import asyncio
    return {"libreoffice": await asyncio.to_thread(libreoffice_runtime.capability)}


@router.post("/api/documents/validate-render")
async def validate_document_render(body: dict = Body(...)):
    import asyncio
    target = os.path.abspath(str(body.get("path") or "").strip())
    allowed = os.path.abspath(_documents_dir())
    try:
        contained = os.path.commonpath((allowed, target)) == allowed
    except ValueError:
        contained = False
    if not contained or not os.path.isfile(target) or not target.casefold().endswith(".docx"):
        raise HTTPException(status_code=400, detail="DOCX Marvin valide requis")
    return await asyncio.to_thread(libreoffice_runtime.validate_docx_render, target)


@router.get("/api/documents/canvas")
async def list_canvas_designs():
    return {"designs": document_canvas.list_designs()}


@router.get("/api/documents/canvas/{design_id}")
async def load_canvas_design(design_id: str):
    try:
        return document_canvas.load(design_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Design introuvable") from exc


@router.post("/api/documents/canvas")
async def save_canvas_design(body: dict = Body(...)):
    try:
        return document_canvas.save(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/documents/canvas/from-prompt")
async def canvas_from_prompt(body: dict = Body(...)):
    try:
        return document_canvas.manifest_from_prompt(body.get("prompt", ""), body.get("title", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/documents/canvas/export/pdf")
async def export_canvas_pdf(body: dict = Body(...)):
    try:
        path = document_canvas.export_pdf(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path, filename=f"{body.get('title') or 'design'}.pdf", media_type="application/pdf")


@router.post("/api/documents/canvas/export/{format_name}")
async def export_canvas_office(format_name: str, body: dict = Body(...)):
    exporters = {"docx": document_canvas.export_docx, "pptx": document_canvas.export_pptx}
    exporter = exporters.get(format_name)
    if exporter is None:
        raise HTTPException(status_code=404, detail="Format non pris en charge")
    try:
        path = exporter(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    media = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }[format_name]
    return FileResponse(path, filename=f"{body.get('title') or 'design'}.{format_name}", media_type=media)


@router.post("/api/documents/generate")
async def generate_document(body: dict = Body(...)):
    result = await _document_tool("document_generate", body)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/api/documents/download")
async def download_document(path: str):
    bases = (_documents_dir(), os.path.join(_DATA_DIR, "documents_generes"))
    target = os.path.abspath(path)
    contained = False
    for base in bases:
        try:
            if os.path.commonpath((base, target)) == os.path.abspath(base):
                contained = True
                break
        except ValueError:
            continue
    if not contained or not os.path.isfile(target):
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
    documents_dir = _documents_dir()
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
    result = await _document_tool("document_index", {"path": body.path})
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


class DocAskBody(BaseModel):
    question: str
    k: int = 6


@router.post("/api/documents/ask")
async def ask_documents(body: DocAskBody):
    result = await _document_tool(
        "document_ask",
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
    result = await _document_tool("document_refine_section", body.model_dump())
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/api/documents/{doc_id}")
async def forget_document(doc_id: str):
    return await _document_tool(
        "document_forget",
        {"id": doc_id},
        confirmed_by_ui=True,
    )


@router.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    documents_dir = os.path.join(_DATA_DIR, "documents")
    os.makedirs(documents_dir, exist_ok=True)
    destination = os.path.join(documents_dir, os.path.basename(file.filename or "document"))
    with open(destination, "wb") as output:
        output.write(await file.read())
    result = await _document_tool("document_index", {"path": destination})
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result
