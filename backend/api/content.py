"""Recherche, navigation locale, aperçus et pièces jointes du chat."""

import base64
import io
import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import tools as tool_module
from platform_paths import system_paths as resolve_system_paths


router = APIRouter(tags=["content"])
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico", ".avif"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".json", ".xml", ".yaml",
    ".yml", ".ini", ".cfg", ".conf", ".env", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".htm", ".css", ".scss", ".sh", ".bat", ".ps1", ".sql", ".rs", ".go",
    ".java", ".c", ".cpp", ".h", ".rst", ".toml",
}


class SearchRequest(BaseModel):
    query: str
    collections: list[str] | None = None
    limit: int = 5


@router.post("/api/search")
async def semantic_search(request: SearchRequest):
    from vector_store import search

    results = await search(request.query, request.collections, request.limit)
    return {"query": request.query, "count": len(results), "results": results}


@router.get("/api/system/paths")
async def system_paths():
    return resolve_system_paths()


@router.get("/api/system/search")
async def system_search_endpoint(query: str = "", file_type: str = "", max_results: int = 30):
    return await tool_module.TOOLS_REGISTRY["system_search"](
        {"query": query, "file_type": file_type, "max_results": max_results}
    )


@router.get("/api/system/search-content")
async def system_search_content_endpoint(
    query: str = "",
    file_type: str = "",
    max_results: int = 25,
):
    return await tool_module.TOOLS_REGISTRY["system_search_content"](
        {"query": query, "file_type": file_type, "max_results": max_results}
    )


@router.get("/api/files/raw")
async def file_raw(path: str):
    absolute_path = os.path.abspath(path)
    if not os.path.isfile(absolute_path):
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    media_type = mimetypes.guess_type(absolute_path)[0] or "application/octet-stream"
    return FileResponse(
        absolute_path,
        media_type=media_type,
        filename=os.path.basename(absolute_path),
    )


@router.get("/api/files/preview")
async def file_preview(path: str):
    absolute_path = os.path.abspath(path)
    if not os.path.isfile(absolute_path):
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    extension = os.path.splitext(absolute_path)[1].lower()
    info = {
        "name": os.path.basename(absolute_path),
        "size": os.path.getsize(absolute_path),
        "ext": extension,
        "path": absolute_path,
    }
    if extension in IMAGE_EXTENSIONS:
        return {**info, "kind": "image"}
    if extension == ".pdf":
        return {**info, "kind": "pdf"}
    if extension == ".docx":
        try:
            result = await tool_module.TOOLS_REGISTRY["docx_to_text"](
                {"path": absolute_path, "format": "markdown"}
            )
            content = result.get("text") or result.get("content") or result.get("markdown") or ""
            return {**info, "kind": "text", "lang": "markdown", "content": content[:200000]}
        except Exception as error:
            return {**info, "kind": "binary", "error": str(error)[:120]}
    if extension in (".xlsx", ".xls"):
        try:
            result = await tool_module.TOOLS_REGISTRY["xlsx_read"]({"path": absolute_path})
            return {**info, "kind": "table", "data": result}
        except Exception:
            return {**info, "kind": "binary"}
    if extension in TEXT_EXTENSIONS:
        try:
            with open(absolute_path, encoding="utf-8", errors="replace") as input_file:
                content = input_file.read(300000)
            return {**info, "kind": "text", "lang": extension.lstrip("."), "content": content}
        except Exception as error:
            return {**info, "kind": "binary", "error": str(error)[:120]}
    return {**info, "kind": "binary"}


@router.post("/api/chat/attach")
async def chat_attach(file: UploadFile = File(...)):
    upload_directory = os.path.abspath(
        os.path.join(os.path.dirname(tool_module.__file__), "..", "data", "chat_uploads")
    )
    os.makedirs(upload_directory, exist_ok=True)
    name = os.path.basename(file.filename or "fichier")
    destination = os.path.join(upload_directory, name)
    with open(destination, "wb") as output:
        output.write(await file.read())

    extension = os.path.splitext(name)[1].lower()
    content = ""
    try:
        if extension == ".pdf":
            result = await tool_module.TOOLS_REGISTRY["pdf_read"]({"path": destination})
            content = result.get("text") or result.get("content") or ""
        elif extension == ".docx":
            result = await tool_module.TOOLS_REGISTRY["docx_to_text"](
                {"path": destination, "format": "markdown"}
            )
            content = result.get("text") or result.get("content") or result.get("markdown") or ""
        elif extension == ".pptx":
            result = await tool_module.TOOLS_REGISTRY["pptx_read"]({"path": destination})
            content = result.get("text") or result.get("content") or ""
        elif extension in (".xlsx", ".xls"):
            result = await tool_module.TOOLS_REGISTRY["xlsx_read"]({"path": destination})
            rows = result.get("data") or []
            headers = result.get("headers") or []
            lines = [" | ".join(str(header) for header in headers)] if headers else []
            for row in rows[:200] if isinstance(rows, list) else []:
                if isinstance(row, dict):
                    lines.append(" | ".join(str(row.get(header, "")) for header in headers))
                elif isinstance(row, list):
                    lines.append(" | ".join(str(cell) for cell in row))
            content = "\n".join(lines)
        elif extension in TEXT_EXTENSIONS:
            with open(destination, encoding="utf-8", errors="replace") as input_file:
                content = input_file.read(40000)
        else:
            return {
                "success": True,
                "name": name,
                "kind": "binary",
                "content": "",
                "chars": 0,
                "message": "Type non lisible directement — joins un PDF, Word, Excel, PowerPoint ou texte.",
            }
    except Exception as error:
        return {"success": False, "error": f"Lecture impossible : {str(error)[:160]}"}

    full_length = len(content or "")
    excerpt = (content or "")[:12000]
    return {
        "success": True,
        "name": name,
        "path": destination,
        "kind": "text",
        "content": excerpt,
        "chars": full_length,
        "truncated": full_length > len(excerpt),
    }


@router.get("/api/search/unified")
async def unified_search_endpoint(query: str = "", scope: str = "", limit: int = 5):
    scopes = [item.strip() for item in scope.split(",") if item.strip()] if scope else None
    args = {"query": query, "limit": limit}
    if scopes:
        args["scope"] = scopes
    return await tool_module.TOOLS_REGISTRY["unified_search"](args)


@router.get("/api/screenshot")
async def take_screenshot():
    try:
        from PIL import ImageGrab

        screenshot = ImageGrab.grab()
        buffer = io.BytesIO()
        screenshot.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return {"success": True, "image": f"data:image/png;base64,{encoded}"}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@router.post("/api/upload-image")
async def upload_image(file: UploadFile = File(...)):
    try:
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        if file.content_type not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Type de fichier non supporté : {file.content_type}",
            )
        data = await file.read()
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image trop volumineuse (max 20 Mo)")
        encoded = base64.b64encode(data).decode("utf-8")
        return {
            "success": True,
            "filename": file.filename,
            "content_type": file.content_type,
            "size": len(data),
            "data": f"data:{file.content_type};base64,{encoded}",
        }
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))
