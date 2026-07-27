"""Outils Google Drive avec transport bloquant isolé hors de la boucle asyncio."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

ServiceFactory = Callable[[], Any]
PathResolver = Callable[[str], str]

_FOLDER_MIME = "application/vnd.google-apps.folder"
_DOC_MIME = "application/vnd.google-apps.document"
_SHEET_MIME = "application/vnd.google-apps.spreadsheet"


def _limit(value: Any, default: int = 30) -> int:
    try:
        return max(1, min(int(value), 1000))
    except (TypeError, ValueError):
        return default


def build_service() -> Any:
    import credentials_manager
    import database
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    access_token = credentials_manager.get_credential("google_access_token")
    refresh_token = credentials_manager.get_credential("google_refresh_token")
    client_id = credentials_manager.get_credential("google_client_id")
    client_secret = credentials_manager.get_credential("google_client_secret")

    if not access_token and not refresh_token:
        try:
            with database.db() as connection:
                row = connection.execute(
                    "SELECT access_token, refresh_token FROM oauth_tokens "
                    "WHERE provider='google'"
                ).fetchone()
            if row:
                access_token = row["access_token"]
                refresh_token = row["refresh_token"]
        except Exception:
            pass
    if not access_token and not refresh_token:
        raise ValueError(
            "Google non connecté. Configurez OAuth dans Paramètres > Connexions."
        )
    credentials = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


async def list_files(
    args: dict[str, Any], *, service_factory: ServiceFactory = build_service
) -> dict[str, Any]:
    folder_id = str(args.get("folder_id") or "root").strip()
    query = str(args.get("query") or "").strip()
    max_results = _limit(args.get("max_results"))
    if not folder_id or len(folder_id) > 256:
        return {"error": "Identifiant de dossier Google Drive invalide."}

    def run() -> list[dict[str, Any]]:
        service = service_factory()
        safe_folder = folder_id.replace("\\", "\\\\").replace("'", "\\'")
        drive_query = f"'{safe_folder}' in parents and trashed=false"
        if query:
            safe_query = query.replace("\\", "\\\\").replace("'", "\\'")
            drive_query += f" and name contains '{safe_query}'"
        response = (
            service.files()
            .list(
                q=drive_query,
                pageSize=max_results,
                fields="files(id, name, mimeType, size, modifiedTime, parents)",
            )
            .execute()
        )
        files = response.get("files", []) if isinstance(response, dict) else []
        return [
            {
                **item,
                "type": "dossier"
                if item.get("mimeType") == _FOLDER_MIME
                else "fichier",
            }
            for item in files
            if isinstance(item, dict)
        ]

    try:
        files = await asyncio.to_thread(run)
        return {"success": True, "count": len(files), "files": files}
    except Exception as exc:
        return {"error": f"Google Drive : {str(exc)[:300]}"}


async def read_file(
    args: dict[str, Any], *, service_factory: ServiceFactory = build_service
) -> dict[str, Any]:
    file_id = str(args.get("file_id") or "").strip()
    if not file_id or len(file_id) > 256:
        return {"error": "file_id requis et limité à 256 caractères."}

    def run() -> dict[str, Any]:
        service = service_factory()
        metadata = (
            service.files()
            .get(fileId=file_id, fields="name,mimeType")
            .execute()
        )
        mime = str(metadata.get("mimeType") or "")
        name = str(metadata.get("name") or "")
        export_mime = {
            _DOC_MIME: "text/plain",
            _SHEET_MIME: "text/csv",
        }.get(mime)
        if not export_mime:
            return {
                "error": f"Type non pris en charge pour la lecture directe : {mime}."
            }
        payload = (
            service.files()
            .export(fileId=file_id, mimeType=export_mime)
            .execute()
        )
        if not isinstance(payload, (bytes, bytearray)):
            return {"error": "Google Drive a retourné un contenu invalide."}
        return {
            "success": True,
            "name": name,
            "content": bytes(payload).decode("utf-8", errors="replace")[:50_000],
        }

    try:
        return await asyncio.to_thread(run)
    except Exception as exc:
        return {"error": f"Google Drive : {str(exc)[:300]}"}


async def upload_file(
    args: dict[str, Any],
    *,
    resolve_path: PathResolver,
    service_factory: ServiceFactory = build_service,
) -> dict[str, Any]:
    raw_path = str(args.get("local_path") or "").strip()
    if not raw_path:
        return {"error": "local_path requis"}
    local_path = Path(resolve_path(raw_path))
    folder_id = str(args.get("folder_id") or "root").strip()
    requested_name = str(args.get("file_name") or "").strip()
    if not folder_id or len(folder_id) > 256:
        return {"error": "Identifiant de dossier Google Drive invalide."}
    if requested_name and (
        len(requested_name) > 255
        or "/" in requested_name
        or "\\" in requested_name
        or requested_name in {".", ".."}
    ):
        return {"error": "file_name doit être un nom simple de 255 caractères maximum."}
    if not local_path.is_file():
        return {"error": f"Fichier introuvable : {local_path}"}

    def run() -> dict[str, Any]:
        from googleapiclient.http import MediaFileUpload

        name = requested_name or local_path.name
        service = service_factory()
        media = MediaFileUpload(str(local_path), resumable=True)
        try:
            response = (
                service.files()
                .create(
                    body={"name": name, "parents": [folder_id]},
                    media_body=media,
                    fields="id,name,webViewLink",
                )
                .execute()
            )
            return {
                "success": True,
                "message": f"Fichier téléversé : {name}",
                "file_id": response.get("id", ""),
                "link": response.get("webViewLink", ""),
            }
        finally:
            stream = media.stream()
            if stream is not None and not stream.closed:
                stream.close()

    try:
        return await asyncio.to_thread(run)
    except Exception as exc:
        return {"error": f"Google Drive : {str(exc)[:300]}"}
