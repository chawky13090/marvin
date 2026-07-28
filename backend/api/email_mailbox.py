"""API des opérations de boîte e-mail IMAP/SMTP et pièces jointes."""

from __future__ import annotations

import asyncio
import urllib.parse

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import database as db
import email_account_service as accounts
import email_manager
import api_errors


router = APIRouter()


class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    cc: str = ""
    reply_to: str = ""
    html_body: str = ""


@router.get("/api/email/inbox")
async def email_inbox(
    folder: str = "INBOX", limit: int = 30, offset: int = 0, account: str | None = None
):
    loop = asyncio.get_running_loop()
    if account == "__all__":
        configs = accounts.list_resolved()
        if not configs:
            return {"error": "Email non configuré", "emails": []}

        async def fetch_one(config: dict):
            try:
                emails = await loop.run_in_executor(
                    None,
                    lambda: email_manager.fetch_inbox(
                        config["imap_host"],
                        int(config.get("imap_port", 993)),
                        config["username"],
                        config["password"],
                        folder=folder,
                        limit=limit,
                        offset=0,
                    ),
                )
                for email in emails:
                    email["_account"] = config["username"]
                return emails
            except Exception:
                return []

        results = await asyncio.gather(*(fetch_one(config) for config in configs))
        merged = [email for batch in results for email in batch]
        merged.sort(key=lambda email: email.get("date") or "", reverse=True)
        return {"emails": merged[: max(limit, 30) * 2], "folder": folder, "unified": True}

    config = accounts.get_resolved(account)
    if not config:
        return {"error": "Email non configuré", "emails": []}

    def fetch():
        emails = email_manager.fetch_inbox(
            config["imap_host"],
            config["imap_port"],
            config["username"],
            config["password"],
            folder=folder,
            limit=limit,
            offset=offset,
        )
        for email in emails:
            email["_account"] = config["username"]
        return emails

    try:
        return {"emails": await loop.run_in_executor(None, fetch), "folder": folder}
    except Exception as exc:
        return api_errors.safe_failure(
            "email_list", exc, "Lecture de la boîte impossible.", emails=[]
        )


@router.get("/api/email/read/{uid}")
async def email_read(uid: str, folder: str = "INBOX", account: str | None = None):
    config = accounts.get_resolved(account)
    if not config:
        raise HTTPException(status_code=400, detail="Email non configuré")
    try:
        return await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: email_manager.fetch_email(
                config["imap_host"], config["imap_port"], config["username"], config["password"],
                uid=uid, folder=folder,
            ),
        )
    except Exception as exc:
        raise api_errors.internal_http_error(
            "email_read", exc, "Lecture du message impossible."
        ) from exc


@router.get("/api/email/search")
async def email_search(
    q: str, folder: str = "INBOX", limit: int = 20, account: str | None = None
):
    loop = asyncio.get_running_loop()
    if account == "__all__":
        async def search_one(config: dict):
            try:
                results = await loop.run_in_executor(
                    None,
                    lambda: email_manager.search_emails(
                        config["imap_host"], int(config.get("imap_port", 993)),
                        config["username"], config["password"], query=q,
                        folder=folder, limit=limit,
                    ),
                )
                for email in results:
                    email["_account"] = config["username"]
                return results
            except Exception:
                return []

        batches = await asyncio.gather(*(search_one(config) for config in accounts.list_resolved()))
        merged = [email for batch in batches for email in batch]
        merged.sort(key=lambda email: email.get("date") or "", reverse=True)
        return {"results": merged, "unified": True}

    config = accounts.get_resolved(account)
    if not config:
        return {"results": [], "error": "Email non configuré"}

    def search():
        results = email_manager.search_emails(
            config["imap_host"], config["imap_port"], config["username"], config["password"],
            query=q, folder=folder, limit=limit,
        )
        for email in results:
            email["_account"] = config["username"]
        return results

    try:
        return {"results": await loop.run_in_executor(None, search)}
    except Exception as exc:
        return api_errors.safe_failure(
            "email_search", exc, "Recherche dans la boîte impossible.", results=[]
        )


@router.get("/api/email/folders")
async def email_folders(account: str | None = None):
    config = accounts.get_resolved(account)
    if not config:
        return {"folders": []}
    try:
        folders = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: email_manager.list_folders(
                config["imap_host"], config["imap_port"], config["username"], config["password"]
            ),
        )
        return {"folders": folders}
    except Exception as exc:
        return api_errors.safe_failure(
            "email_folders", exc, "Lecture des dossiers impossible.", folders=[]
        )


@router.post("/api/email/send")
async def email_send(body: SendEmailRequest, account: str | None = None):
    config = accounts.get_resolved(account)
    if not config:
        raise HTTPException(status_code=400, detail="Email non configuré")
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: email_manager.send_email(
                config["smtp_host"], config["smtp_port"], config["username"], config["password"],
                to=body.to, subject=body.subject, body=body.body, cc=body.cc,
                reply_to=body.reply_to, html_body=body.html_body,
            ),
        )
        db.log_execution("email_send", {"to": body.to, "subject": body.subject}, result, 0)
        return result
    except Exception as exc:
        raise api_errors.internal_http_error(
            "email_send", exc, "Envoi du message impossible."
        ) from exc


@router.delete("/api/email/{uid}")
async def email_delete(uid: str, folder: str = "INBOX", account: str | None = None):
    config = accounts.get_resolved(account)
    if not config:
        raise HTTPException(status_code=400, detail="Email non configuré")
    await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: email_manager.delete_email(
            config["imap_host"], config["imap_port"], config["username"], config["password"],
            uid=uid, folder=folder,
        ),
    )
    return {"success": True}


@router.post("/api/email/mark")
async def email_mark(
    uid: str, seen: bool = True, folder: str = "INBOX", account: str | None = None
):
    config = accounts.get_resolved(account)
    if not config:
        raise HTTPException(status_code=400, detail="Email non configuré")
    try:
        await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: email_manager.mark_email(
                config["imap_host"], config["imap_port"], config["username"], config["password"],
                uid=uid, folder=folder, seen=seen,
            ),
        )
        return {"success": True, "seen": seen}
    except Exception as exc:
        raise api_errors.internal_http_error(
            "email_mark", exc, "Modification du message impossible."
        ) from exc


@router.post("/api/email/move")
async def email_move(
    uid: str, dest: str, folder: str = "INBOX", account: str | None = None
):
    config = accounts.get_resolved(account)
    if not config:
        raise HTTPException(status_code=400, detail="Email non configuré")
    try:
        await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: email_manager.move_email(
                config["imap_host"], config["imap_port"], config["username"], config["password"],
                uid=uid, dest_folder=dest, folder=folder,
            ),
        )
        return {"success": True, "dest": dest}
    except Exception as exc:
        raise api_errors.internal_http_error(
            "email_move", exc, "Déplacement du message impossible."
        ) from exc


@router.get("/api/email/attachment")
async def email_attachment(
    uid: str, name: str = "", account: str | None = None, folder: str = "INBOX"
):
    config = accounts.get_resolved(account)
    if not config:
        raise HTTPException(status_code=400, detail="Email non configuré")
    attachment = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: email_manager.fetch_attachment(
            config["imap_host"], config["imap_port"], config["username"], config["password"],
            uid=uid, name=name, folder=folder,
        ),
    )
    if not attachment or not attachment.get("data"):
        raise HTTPException(status_code=404, detail="Pièce jointe introuvable")
    filename = urllib.parse.quote(attachment["name"] or "piece_jointe")
    return Response(
        content=attachment["data"],
        media_type=attachment.get("content_type", "application/octet-stream"),
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
