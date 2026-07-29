"""Jumelage et état de la session LAN Marvin."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from lan_access import (
    ACCESS,
    CSRF_COOKIE,
    SESSION_COOKIE,
    LanAccessError,
    effective_client,
    is_loopback,
    required_capability,
)


router = APIRouter(prefix="/api/auth/lan", tags=["access"])
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class PairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: StrictStr = Field(min_length=12, max_length=128)
    access_profile: Literal["read_only", "standard", "full"] = "standard"


class IntrospectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: StrictStr = Field(min_length=1, max_length=512, pattern=r"^/api(?:/|$)")
    method: Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]


def _set_session_cookies(
    response: Response,
    *,
    token: str,
    csrf: str,
    secure: bool,
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


def _audit_pair(success: bool, *, error_code: str | None = None) -> None:
    try:
        import audit

        audit.log_action(
            "lan_pair",
            result={"success": success, "error": error_code},
            source="runtime",
        )
    except Exception:
        pass


def _https_status() -> dict:
    state_path = _PROJECT_ROOT / "runtime" / "https" / "state.json"
    root_path = (
        _PROJECT_ROOT
        / "runtime"
        / "https"
        / "data"
        / "pki"
        / "authorities"
        / "local"
        / "root.crt"
    )
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        state = {}
    result = {
        "configured": bool(state.get("enabled")),
        "port": state.get("port"),
        "origins": state.get("origins") if isinstance(state.get("origins"), list) else [],
    }
    try:
        result["root_sha256"] = hashlib.sha256(root_path.read_bytes()).hexdigest()
    except OSError:
        result["root_sha256"] = None
    return result


@router.get("/status")
async def lan_status(request: Request, response: Response):
    headers = {key.casefold(): value for key, value in request.headers.items()}
    client = effective_client(request.client.host if request.client else "", headers)
    session = ACCESS.authenticated(headers, client=client)
    authenticated = is_loopback(client) or session is not None
    if is_loopback(client) and session is None:
        token, csrf = ACCESS.issue(client)
        _set_session_cookies(
            response,
            token=token,
            csrf=csrf,
            secure=request.url.scheme == "https",
        )
    result = {
        "required": not is_loopback(client),
        "authenticated": authenticated,
        "transport_secure": request.url.scheme == "https",
    }
    if session is not None:
        result["access_profile"] = session["profile"]
    if is_loopback(client):
        result["pairing_code"] = ACCESS.pairing_code
        result["pairing_expires_in_seconds"] = 300 if ACCESS.pairing_code else 0
    if is_loopback(client) or session is not None:
        result["https"] = _https_status()
    return result


@router.post("/pairing-code")
async def regenerate_pairing_code(request: Request):
    headers = {key.casefold(): value for key, value in request.headers.items()}
    client = effective_client(request.client.host if request.client else "", headers)
    if not is_loopback(client):
        raise HTTPException(status_code=403, detail="Action réservée au PC principal.")
    code = ACCESS.regenerate_pairing_code()
    _audit_pair(True, error_code="pairing_code_regenerated")
    return {"pairing_code": code, "expires_in_seconds": 300}


@router.get("/ca-certificate")
async def download_ca_certificate():
    certificate = (
        _PROJECT_ROOT
        / "runtime"
        / "https"
        / "data"
        / "pki"
        / "authorities"
        / "local"
        / "root.crt"
    )
    if not certificate.is_file():
        raise HTTPException(status_code=404, detail="Autorité HTTPS non configurée.")
    return FileResponse(
        certificate,
        media_type="application/x-x509-ca-cert",
        filename="marvin-local-authority.crt",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/introspect")
async def lan_introspect(
    payload: IntrospectRequest,
    request: Request,
    response: Response,
):
    """Valide la signature d'une session pour le proxy Next.js local."""
    headers = {key.casefold(): value for key, value in request.headers.items()}
    response.headers["Cache-Control"] = "no-store"
    session = ACCESS.authenticated(headers)
    capability = required_capability(payload.path, payload.method)
    return {
        "authenticated": session is not None,
        "authorized": (
            session is not None and ACCESS.authorized(session, capability)
        ),
        "required_capability": capability,
    }


@router.post("/pair")
async def lan_pair(payload: PairRequest, request: Request, response: Response):
    headers = {key.casefold(): value for key, value in request.headers.items()}
    client = effective_client(request.client.host if request.client else "", headers)
    try:
        token, csrf = ACCESS.pair(
            client,
            payload.code,
            profile=payload.access_profile,
        )
    except LanAccessError as exc:
        _audit_pair(False, error_code=type(exc).__name__)
        raise HTTPException(status_code=401, detail="Jumelage refusé.") from exc
    secure = request.url.scheme == "https"
    _set_session_cookies(response, token=token, csrf=csrf, secure=secure)
    _audit_pair(True)
    return {
        "success": True,
        "authenticated": True,
        "transport_secure": secure,
        "access_profile": payload.access_profile,
    }


@router.post("/logout")
async def lan_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.headers["Cache-Control"] = "no-store"
    try:
        import audit

        audit.log_action(
            "lan_logout",
            result={"success": True},
            source="runtime",
        )
    except Exception:
        pass
    return {"success": True, "authenticated": False}
