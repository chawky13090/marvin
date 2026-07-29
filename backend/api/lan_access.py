"""Jumelage et état de la session LAN Marvin."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from lan_access import (
    ACCESS,
    CSRF_COOKIE,
    SESSION_COOKIE,
    LanAccessError,
    is_loopback,
)


router = APIRouter(prefix="/api/auth/lan", tags=["access"])


class PairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: StrictStr = Field(min_length=12, max_length=128)


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


@router.get("/status")
async def lan_status(request: Request, response: Response):
    client = request.client.host if request.client else ""
    headers = {key.casefold(): value for key, value in request.headers.items()}
    authenticated = (
        is_loopback(client)
        or ACCESS.authenticated(headers, client=client) is not None
    )
    if is_loopback(client) and ACCESS.authenticated(headers, client=client) is None:
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
    if is_loopback(client):
        result["pairing_code"] = ACCESS.pairing_code
    return result


@router.post("/introspect")
async def lan_introspect(request: Request, response: Response):
    """Valide la signature d'une session pour le proxy Next.js local."""
    headers = {key.casefold(): value for key, value in request.headers.items()}
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": ACCESS.authenticated(headers) is not None}


@router.post("/pair")
async def lan_pair(payload: PairRequest, request: Request, response: Response):
    client = request.client.host if request.client else ""
    try:
        token, csrf = ACCESS.pair(client, payload.code)
    except LanAccessError as exc:
        _audit_pair(False, error_code=type(exc).__name__)
        raise HTTPException(status_code=401, detail="Jumelage refusé.") from exc
    secure = request.url.scheme == "https"
    _set_session_cookies(response, token=token, csrf=csrf, secure=secure)
    _audit_pair(True)
    return {"success": True, "authenticated": True, "transport_secure": secure}


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
