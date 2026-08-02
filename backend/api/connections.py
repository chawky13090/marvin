"""Identifiants masqués et flux OAuth Google/Microsoft."""

import urllib.parse
import secrets
import time

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

import credentials_manager as credentials
from secret_vault import SecretVaultError
import database as db
import tools as tool_module
import email_accounts
import google_service_account_vault
from config import BACKEND_PORT


router = APIRouter(tags=["connections"])
GOOGLE_CALLBACK = f"http://localhost:{BACKEND_PORT}/api/oauth/google/callback"
MICROSOFT_CALLBACK = f"http://localhost:{BACKEND_PORT}/api/oauth/microsoft/callback"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
]
GMAIL_IMAP_SCOPES = ["https://mail.google.com/"]


@router.get("/api/credentials")
async def get_credentials():
    try:
        return {
            "credentials": credentials.get_all_credentials(),
            "groups": credentials.get_group_status(),
            "security": credentials.security_status(),
        }
    except SecretVaultError as exc:
        raise HTTPException(
            status_code=503,
            detail="Le coffre sécurisé Windows est indisponible.",
        ) from exc


class CredentialSetRequest(BaseModel):
    value: str = Field(min_length=0, max_length=16_384)


@router.put("/api/credentials/{name}")
async def set_credential(name: str, body: CredentialSetRequest):
    if name not in credentials.CREDENTIAL_DEFINITIONS:
        raise HTTPException(status_code=404, detail=f"Credential inconnu : {name}")
    try:
        credentials.set_credential(name, body.value)
    except (SecretVaultError, ValueError) as exc:
        raise HTTPException(
            status_code=503 if isinstance(exc, SecretVaultError) else 422,
            detail=(
                "Le coffre sécurisé Windows est indisponible."
                if isinstance(exc, SecretVaultError)
                else str(exc)
            ),
        ) from exc
    return {"success": True}


@router.delete("/api/credentials/{name}")
async def delete_credential(name: str):
    if name not in credentials.CREDENTIAL_DEFINITIONS:
        raise HTTPException(status_code=404, detail=f"Credential inconnu : {name}")
    try:
        credentials.delete_credential(name)
    except SecretVaultError as exc:
        raise HTTPException(
            status_code=503,
            detail="Le coffre sécurisé Windows est indisponible.",
        ) from exc
    return {"success": True}


@router.get("/api/credentials/security")
async def get_credentials_security():
    try:
        return credentials.security_status()
    except SecretVaultError as exc:
        raise HTTPException(
            status_code=503,
            detail="Le coffre sécurisé Windows est indisponible.",
        ) from exc


def _google_flow():
    from google_auth_oauthlib.flow import Flow

    client_id = credentials.get_credential("google_client_id")
    client_secret = credentials.get_credential("google_client_secret")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail="Client ID et Client Secret Google requis",
        )
    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [GOOGLE_CALLBACK],
            }
        },
        scopes=GOOGLE_SCOPES,
    )
    flow.redirect_uri = GOOGLE_CALLBACK
    return flow


def _gmail_flow():
    """OAuth dédié aux boîtes mail : le scope IMAP/SMTP XOAUTH2 est distinct de Calendar."""
    from google_auth_oauthlib.flow import Flow

    client_id = credentials.get_credential("google_client_id")
    client_secret = credentials.get_credential("google_client_secret")
    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="Client ID et Client Secret Google requis")
    flow = Flow.from_client_config(
        client_config={"web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [f"{GOOGLE_CALLBACK}/email"],
        }},
        scopes=GMAIL_IMAP_SCOPES,
    )
    flow.redirect_uri = f"{GOOGLE_CALLBACK}/email"
    return flow


@router.get("/api/email/oauth/google/start")
async def gmail_oauth_start(account_hint: str = ""):
    state = secrets.token_urlsafe(24)
    states = db.get_setting("email_oauth_states") or {}
    if not isinstance(states, dict):
        states = {}
    now = int(time.time())
    states = {key: value for key, value in states.items()
              if isinstance(value, dict) and now - int(value.get("created_at", 0)) < 900}
    states[state] = {"created_at": now, "account_hint": account_hint.strip()}
    db.set_setting("email_oauth_states", states)
    kwargs = {"access_type": "offline", "prompt": "consent", "state": state}
    if account_hint.strip():
        kwargs["login_hint"] = account_hint.strip()
    authorization_url, _ = _gmail_flow().authorization_url(**kwargs)
    return {"auth_url": authorization_url}


@router.get("/api/oauth/google/callback/email")
async def gmail_oauth_callback(code: str, state: str):
    states = db.get_setting("email_oauth_states") or {}
    record = states.pop(state, None) if isinstance(states, dict) else None
    db.set_setting("email_oauth_states", states if isinstance(states, dict) else {})
    if not record or int(time.time()) - int(record.get("created_at", 0)) >= 900:
        raise HTTPException(status_code=400, detail="Autorisation OAuth expirée ou invalide")
    flow = _gmail_flow()
    flow.fetch_token(code=code)
    oauth = flow.credentials
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {oauth.token}"},
        )
        response.raise_for_status()
        username = response.json().get("emailAddress")
    if not username:
        raise HTTPException(status_code=400, detail="Adresse Gmail introuvable")
    email_accounts.upsert({
        "provider": "gmail",
        "auth_type": "oauth2",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "username": username,
        "password": "",
        "access_token": oauth.token,
        "refresh_token": oauth.refresh_token,
        "token_expiry": oauth.expiry.isoformat() if oauth.expiry else None,
        "oauth_client_id": credentials.get_credential("google_client_id"),
        "oauth_client_secret": credentials.get_credential("google_client_secret"),
        "oauth_scopes": GMAIL_IMAP_SCOPES,
    })
    return RedirectResponse(url="http://localhost:3000/emails?email_oauth=connected")


@router.get("/api/oauth/google/start")
async def google_oauth_start():
    authorization_url, _ = _google_flow().authorization_url(
        access_type="offline",
        prompt="consent",
    )
    return {"auth_url": authorization_url}


@router.get("/api/oauth/google/connect")
async def google_oauth_connect():
    result = await google_oauth_start()
    if result.get("auth_url"):
        return RedirectResponse(url=result["auth_url"])
    raise HTTPException(
        status_code=400,
        detail="Impossible de générer l'URL d'autorisation Google.",
    )


@router.get("/api/oauth/google/callback")
async def google_oauth_callback(code: str):
    flow = _google_flow()
    flow.fetch_token(code=code)
    oauth_credentials = flow.credentials
    credentials.set_credential("google_access_token", oauth_credentials.token)
    if oauth_credentials.refresh_token:
        credentials.set_credential("google_refresh_token", oauth_credentials.refresh_token)
    return RedirectResponse(
        url="http://localhost:3000/settings?tab=connections&google=connected"
    )


@router.get("/api/oauth/google/status")
async def google_oauth_status():
    service_account_email = tool_module._google_sa_email()
    calendar_id = db.get_setting("google_calendar_id")
    mode = "service_account" if service_account_email else "oauth"
    connected = False
    email = None
    error = None
    count = None

    if service_account_email:
        if not calendar_id:
            error = "Clé de service OK, mais l'agenda cible n'est pas défini (ton email)."
        else:
            try:
                service = tool_module._get_google_calendar_service()
                response = service.events().list(calendarId=calendar_id, maxResults=1).execute()
                email = calendar_id
                count = len(response.get("items", []))
                connected = True
            except Exception as exception:
                error = str(exception)[:200]
        return {
            "mode": mode,
            "has_keys": True,
            "connected": connected,
            "email": email,
            "sa_email": service_account_email,
            "calendar_id": calendar_id,
            "sample_count": count,
            "error": error,
            "next_step": None if connected else (
                "Définis l'agenda cible (ton email) : POST /api/google/calendar-id."
                if not calendar_id
                else f"Partage ton Google Agenda avec {service_account_email} (droit « Modifier les événements »)."
            ),
        }

    has_keys = bool(
        credentials.get_credential("google_client_id")
        and credentials.get_credential("google_client_secret")
    )
    access_token = credentials.get_credential("google_access_token")
    refresh_token = credentials.get_credential("google_refresh_token")
    source = "backend"
    has_tokens = bool(access_token or refresh_token)
    if has_tokens:
        try:
            service = tool_module._get_google_calendar_service()
            calendar = service.calendarList().get(calendarId="primary").execute()
            email = calendar.get("id")
            connected = True
        except Exception as exception:
            error = str(exception)[:160]
    return {
        "mode": mode,
        "has_keys": has_keys,
        "has_tokens": has_tokens,
        "connected": connected,
        "has_refresh": bool(refresh_token),
        "email": email,
        "source": source if has_tokens else None,
        "callback_uri": GOOGLE_CALLBACK,
        "error": error,
        "next_step": None if connected else (
            "Termine l'autorisation : ouvre /api/oauth/google/connect."
            if has_keys
            else "Renseigne Client ID et Secret, ou utilise un compte de service."
        ),
    }


@router.post("/api/oauth/google/service-account")
async def upload_google_service_account(file: UploadFile = File(...)):
    raw = await file.read(google_service_account_vault.MAX_BYTES + 1)
    try:
        result = google_service_account_vault.store(raw)
    except google_service_account_vault.GoogleServiceAccountVaultError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    client_email = result["client_email"]
    return {
        "success": True,
        "client_email": client_email,
        "storage": "windows_dpapi_current_user",
        "share_hint": (
            f"Partage maintenant ton Google Agenda avec {client_email} "
            "(droit « Modifier les événements »), puis définis ton email comme agenda cible."
        ),
    }


@router.delete("/api/oauth/google/service-account")
async def delete_google_service_account():
    try:
        google_service_account_vault.delete()
    except google_service_account_vault.GoogleServiceAccountVaultError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "storage": "windows_dpapi_current_user"}


class CalendarIdBody(BaseModel):
    calendar_id: str


@router.post("/api/google/calendar-id")
async def set_google_calendar_id(body: CalendarIdBody):
    calendar_id = body.calendar_id.strip()
    db.set_setting("google_calendar_id", calendar_id)
    return {"success": True, "calendar_id": calendar_id}


@router.get("/api/oauth/microsoft/start")
async def microsoft_oauth_start():
    client_id = credentials.get_credential("ms_client_id")
    tenant_id = credentials.get_credential("ms_tenant_id") or "common"
    if not client_id:
        raise HTTPException(status_code=400, detail="Client ID Microsoft requis")
    parameters = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": MICROSOFT_CALLBACK,
        "scope": "https://graph.microsoft.com/Files.ReadWrite offline_access",
        "response_mode": "query",
    }
    return {
        "auth_url": (
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?"
            + urllib.parse.urlencode(parameters)
        )
    }


@router.get("/api/oauth/microsoft/callback")
async def microsoft_oauth_callback(code: str):
    client_id = credentials.get_credential("ms_client_id")
    client_secret = credentials.get_credential("ms_client_secret") or ""
    tenant_id = credentials.get_credential("ms_tenant_id") or "common"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": MICROSOFT_CALLBACK,
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/Files.ReadWrite offline_access",
            },
        )
        response.raise_for_status()
        data = response.json()
    credentials.set_credential("ms_access_token", data["access_token"])
    if "refresh_token" in data:
        credentials.set_credential("ms_refresh_token", data["refresh_token"])
    return RedirectResponse(
        url="http://localhost:3000/settings?tab=connections&microsoft=connected"
    )
