"""Outils OneDrive fondés sur Microsoft Graph v1.0."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

TokenGetter = Callable[[], Awaitable[str]]
Requester = Callable[..., Awaitable[Any]]
PathResolver = Callable[[str], str]

_GRAPH = "https://graph.microsoft.com/v1.0"
_TENANT_RE = re.compile(r"^(?:common|organizations|consumers|[0-9a-fA-F-]{36})$")
_SIMPLE_UPLOAD_MAX = 250 * 1024 * 1024
_READ_MAX = 50_000
_INVALID_REMOTE_CHARS = set('\\:*?"<>|')


def _limit(value: Any, default: int = 30) -> int:
    try:
        return max(1, min(int(value), 999))
    except (TypeError, ValueError):
        return default


async def get_token() -> str:
    import credentials_manager
    import httpx

    access_token = credentials_manager.get_credential("ms_access_token")
    refresh_token = credentials_manager.get_credential("ms_refresh_token")
    client_id = credentials_manager.get_credential("ms_client_id")
    client_secret = credentials_manager.get_credential("ms_client_secret")
    tenant_id = str(
        credentials_manager.get_credential("ms_tenant_id") or "common"
    ).strip()
    if access_token:
        return str(access_token)
    if not refresh_token:
        raise ValueError(
            "Microsoft non connecté. Configurez OAuth dans Paramètres > Connexions."
        )
    if not client_id:
        raise ValueError("Le client_id Microsoft est requis pour renouveler le jeton.")
    if not _TENANT_RE.fullmatch(tenant_id):
        raise ValueError("Le tenant_id Microsoft configuré est invalide.")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0)
    ) as client:
        response = await client.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret or "",
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        response.raise_for_status()
        payload = response.json()
    new_token = payload.get("access_token")
    if not new_token:
        raise ValueError("Microsoft n'a pas retourné de jeton d'accès.")
    credentials_manager.set_credential("ms_access_token", new_token)
    if payload.get("refresh_token"):
        credentials_manager.set_credential(
            "ms_refresh_token", payload["refresh_token"]
        )
    return str(new_token)


async def _request(method: str, url: str, **kwargs: Any) -> Any:
    import httpx

    timeout = kwargs.pop("timeout", 20.0)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=5.0), follow_redirects=True
    ) as client:
        return await client.request(method, url, **kwargs)


def _remote_path(value: Any) -> str:
    path = str(value or "").strip().replace("\\", "/").strip("/")
    if not path or len(path) > 1024:
        raise ValueError("Le chemin distant OneDrive est vide ou trop long.")
    parts = path.split("/")
    if any(
        part in {"", ".", ".."}
        or len(part) > 255
        or any(char in _INVALID_REMOTE_CHARS for char in part)
        for part in parts
    ):
        raise ValueError("Le chemin distant OneDrive contient un segment interdit.")
    return path


async def list_files(
    args: dict[str, Any],
    *,
    token_getter: TokenGetter = get_token,
    requester: Requester = _request,
) -> dict[str, Any]:
    folder_id = str(args.get("folder_id") or "root").strip()
    query = str(args.get("query") or "").strip()
    max_results = _limit(args.get("max_results"))
    if not folder_id or len(folder_id) > 256:
        return {"error": "Identifiant de dossier OneDrive invalide."}
    try:
        token = await token_getter()
        headers = {"Authorization": f"Bearer {token}"}
        if query:
            if len(query) > 500:
                return {"error": "La recherche OneDrive est limitée à 500 caractères."}
            escaped = query.replace("'", "''")
            expression = quote(f"q='{escaped}'", safe="='")
            url = f"{_GRAPH}/me/drive/root/search({expression})"
        else:
            safe_id = quote(folder_id, safe="")
            url = f"{_GRAPH}/me/drive/items/{safe_id}/children"
        response = await requester(
            "GET", url, headers=headers, params={"$top": max_results}, timeout=20.0
        )
        response.raise_for_status()
        payload = response.json()
        raw_items = payload.get("value", []) if isinstance(payload, dict) else []
        files = [
            {
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "type": "dossier" if "folder" in item else "fichier",
                "size": max(0, int(item.get("size") or 0)),
                "modified": item.get("lastModifiedDateTime", ""),
                "web_url": item.get("webUrl", ""),
            }
            for item in raw_items
            if isinstance(item, dict)
        ]
        return {"success": True, "count": len(files), "files": files}
    except Exception as exc:
        return {"error": f"OneDrive : {str(exc)[:300]}"}


async def read_file(
    args: dict[str, Any],
    *,
    token_getter: TokenGetter = get_token,
    requester: Requester = _request,
) -> dict[str, Any]:
    file_id = str(args.get("file_id") or "").strip()
    if not file_id or len(file_id) > 256:
        return {"error": "file_id requis et limité à 256 caractères."}
    try:
        token = await token_getter()
        response = await requester(
            "GET",
            f"{_GRAPH}/me/drive/items/{quote(file_id, safe='')}/content",
            headers={
                "Authorization": f"Bearer {token}",
                "Range": f"bytes=0-{_READ_MAX - 1}",
            },
            timeout=20.0,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if not (
            content_type.startswith("text/")
            or "json" in content_type
            or "xml" in content_type
            or "csv" in content_type
        ):
            return {"error": "Contenu binaire non pris en charge pour lecture directe."}
        raw = bytes(response.content[:_READ_MAX])
        return {
            "success": True,
            "content": raw.decode(response.encoding or "utf-8", errors="replace"),
            "truncated": len(response.content) >= _READ_MAX,
        }
    except Exception as exc:
        return {"error": f"OneDrive : {str(exc)[:300]}"}


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    handle = path.open("rb")
    try:
        while True:
            chunk = await asyncio.to_thread(handle.read, 1024 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        handle.close()


async def upload_file(
    args: dict[str, Any],
    *,
    resolve_path: PathResolver,
    token_getter: TokenGetter = get_token,
    requester: Requester = _request,
) -> dict[str, Any]:
    raw_path = str(args.get("local_path") or "").strip()
    if not raw_path:
        return {"error": "local_path requis"}
    local_path = Path(resolve_path(raw_path))
    if not local_path.is_file():
        return {"error": f"Fichier introuvable : {local_path}"}
    try:
        destination = _remote_path(args.get("dest_path") or local_path.name)
    except ValueError as exc:
        return {"error": str(exc)}
    size = local_path.stat().st_size
    if size > _SIMPLE_UPLOAD_MAX:
        return {
            "error": "L'upload simple OneDrive est limité à 250 Mo. "
            "Une session d'upload fragmentée est requise pour ce fichier."
        }
    try:
        token = await token_getter()
        encoded_path = quote(destination, safe="/")
        chunks = _file_chunks(local_path)
        try:
            response = await requester(
                "PUT",
                f"{_GRAPH}/me/drive/root:/{encoded_path}:/content",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(size),
                },
                content=chunks,
                timeout=300.0,
            )
        finally:
            await chunks.aclose()
        response.raise_for_status()
        payload = response.json()
        return {
            "success": True,
            "message": f"Fichier téléversé : {destination}",
            "file_id": payload.get("id", ""),
            "web_url": payload.get("webUrl", ""),
        }
    except Exception as exc:
        return {"error": f"OneDrive : {str(exc)[:300]}"}
