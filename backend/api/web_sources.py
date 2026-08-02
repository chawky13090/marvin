"""Aperçus privés des sources Web affichées dans le chat."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from web_source_metadata import cache_preview


router = APIRouter(tags=["web-sources"])


@router.get("/api/web/source-preview")
async def source_preview(url: str = Query(min_length=10, max_length=4_096)):
    try:
        path, media_type = await cache_preview(url)
    except (OSError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=86400, stale-while-revalidate=86400, stale-if-error=604800",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
