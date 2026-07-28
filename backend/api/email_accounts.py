"""API de configuration et de gestion multi-comptes e-mail."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel, Field

import email_account_service as accounts
import email_manager


router = APIRouter()


class EmailConfig(BaseModel):
    provider: str = Field(default="custom", min_length=1, max_length=64)
    imap_host: str = Field(min_length=1, max_length=253)
    imap_port: int = Field(default=993, ge=1, le=65535)
    smtp_host: str = Field(min_length=1, max_length=253)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    username: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=12_000)


@router.get("/api/email/providers")
async def email_providers():
    return email_manager.PROVIDERS


@router.get("/api/email/config")
async def get_email_config(account: str | None = None):
    return accounts.public_config(account)


@router.post("/api/email/config")
async def set_email_config(body: EmailConfig):
    accounts.upsert_app_password(body.model_dump())
    return {"success": True}


@router.get("/api/email/accounts")
async def email_accounts_list():
    return accounts.list_public()


@router.post("/api/email/accounts")
async def email_accounts_add(body: EmailConfig):
    saved = accounts.upsert_app_password(body.model_dump())
    return {"success": True, "id": body.username, "count": len(saved)}


@router.delete("/api/email/accounts/{account_id}")
async def email_accounts_remove(account_id: str):
    return accounts.remove(account_id)


@router.post("/api/email/test")
async def test_email_config(body: EmailConfig):
    def test_connection():
        return email_manager.test_connection(
            body.imap_host,
            body.imap_port,
            body.smtp_host,
            body.smtp_port,
            body.username,
            body.password,
        )

    return await asyncio.get_running_loop().run_in_executor(None, test_connection)
