"""Erreurs API internes expurgées et corrélables."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException

import api_observability
import bug_log


def _incident(
    component: str,
    exc: BaseException,
    public_message: str,
) -> tuple[str, str, str]:
    incident_id = uuid.uuid4().hex
    request_id = api_observability.current_request_id() or uuid.uuid4().hex
    message = str(public_message or "Une erreur interne est survenue.").strip()[:300]
    bug_log.log_bug(
        f"api_{str(component or 'unknown')[:100]}",
        type(exc).__name__,
        context={
            "incident_id": incident_id,
            "request_id": request_id,
            "exception_type": type(exc).__name__[:160],
        },
    )
    return incident_id, request_id, message


def internal_http_error(
    component: str,
    exc: BaseException,
    public_message: str = "Une erreur interne est survenue.",
) -> HTTPException:
    incident_id, request_id, message = _incident(component, exc, public_message)
    return HTTPException(
        status_code=500,
        detail=f"{message} Incident : {incident_id}.",
        headers={
            "X-Incident-ID": incident_id,
            "X-Request-ID": request_id,
        },
    )


def safe_failure(
    component: str,
    exc: BaseException,
    public_message: str = "Une erreur interne est survenue.",
    **fields: Any,
) -> dict[str, Any]:
    incident_id, request_id, message = _incident(component, exc, public_message)
    return {
        **fields,
        "error": f"{message} Incident : {incident_id}.",
        "incident_id": incident_id,
        "request_id": request_id,
    }
