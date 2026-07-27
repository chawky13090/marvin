"""Connecteurs ITSM, avec GLPI comme backend actuellement certifié."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

Request = Callable[..., Awaitable[dict[str, Any]]]
_BACKENDS = {"glpi"}


def _limit(value: Any, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


async def glpi_request(
    method: str,
    endpoint: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import credentials_manager
    import httpx

    base_url = str(credentials_manager.get_credential("glpi_url") or "").rstrip("/")
    app_token = str(credentials_manager.get_credential("glpi_app_token") or "")
    user_token = str(credentials_manager.get_credential("glpi_user_token") or "")
    parsed = urlparse(base_url)
    if not base_url or not app_token or not user_token:
        return {
            "error": "GLPI non configuré. Renseignez glpi_url, glpi_app_token et "
            "glpi_user_token dans Réglages > Connexions."
        }
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"error": "L'URL GLPI configurée est invalide."}

    session_headers: dict[str, str] | None = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            init = await client.get(
                f"{base_url}/apirest.php/initSession",
                headers={
                    "Authorization": f"user_token {user_token}",
                    "App-Token": app_token,
                },
            )
            if init.status_code != 200:
                return {
                    "error": f"Connexion GLPI échouée (HTTP {init.status_code}) : "
                    f"{init.text[:200]}"
                }
            session_token = str(init.json().get("session_token") or "")
            if not session_token:
                return {"error": "GLPI n'a pas retourné de jeton de session."}
            session_headers = {
                "Session-Token": session_token,
                "App-Token": app_token,
            }
            response = await client.request(
                method,
                f"{base_url}/apirest.php/{endpoint}",
                headers=session_headers,
                json=json_body,
                params=params,
            )
            try:
                data = response.json() if response.content else {}
            except ValueError:
                data = {"response": response.text[:300]}
            if response.status_code >= 400:
                return {
                    "error": f"GLPI a refusé la requête (HTTP {response.status_code}) : "
                    f"{str(data)[:300]}"
                }
            return {"success": True, "data": data}
    except Exception as exc:
        return {"error": f"Erreur de connexion à GLPI : {str(exc)[:300]}"}
    finally:
        if session_headers is not None:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(5.0, connect=3.0)
                ) as cleanup_client:
                    await cleanup_client.get(
                        f"{base_url}/apirest.php/killSession",
                        headers=session_headers,
                    )
            except Exception:
                pass


def _system(args: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    system = str(args.get("system") or "glpi").strip().lower()
    if system not in _BACKENDS:
        return system, {
            "error": f"Système '{system}' non implémenté "
            f"(disponibles : {', '.join(sorted(_BACKENDS))})."
        }
    return system, None


async def ticket_list(
    args: dict[str, Any], *, request: Request = glpi_request
) -> dict[str, Any]:
    system, error = _system(args)
    if error:
        return error
    limit = _limit(args.get("limit"), 20, 100)
    result = await request("GET", "Ticket", params={"range": f"0-{limit - 1}"})
    if result.get("error"):
        return result
    tickets = result.get("data") if isinstance(result.get("data"), list) else []
    return {
        "success": True,
        "system": system,
        "count": len(tickets),
        "tickets": [
            {
                "id": ticket.get("id"),
                "title": ticket.get("name"),
                "status": ticket.get("status"),
                "urgency": ticket.get("urgency"),
                "date": ticket.get("date"),
            }
            for ticket in tickets
            if isinstance(ticket, dict)
        ],
    }


async def ticket_create(
    args: dict[str, Any], *, request: Request = glpi_request
) -> dict[str, Any]:
    system, error = _system(args)
    if error:
        return error
    title = str(args.get("title") or "").strip()
    description = str(args.get("description") or "").strip()
    if not title:
        return {"error": "Paramètre 'title' requis."}
    if len(title) > 255 or len(description) > 20_000:
        return {"error": "Titre limité à 255 caractères et description à 20 000."}
    if not args.get("confirmed"):
        return {
            "requiresConfirmation": True,
            "message": f"Créer un ticket {system.upper()} — « {title} » ?\n\n"
            f"{description[:300]}",
        }
    payload: dict[str, Any] = {"input": {"name": title, "content": description}}
    urgency_value = args.get("urgency")
    if urgency_value not in (None, ""):
        try:
            urgency = int(urgency_value)
        except (TypeError, ValueError):
            return {"error": "L'urgence doit être un entier de 1 à 5."}
        if urgency not in range(1, 6):
            return {"error": "L'urgence doit être comprise entre 1 et 5."}
        payload["input"]["urgency"] = urgency
    result = await request("POST", "Ticket", json_body=payload)
    if result.get("error"):
        return result
    data = result.get("data")
    ticket_id = data.get("id") if isinstance(data, dict) else None
    return {
        "success": True,
        "system": system,
        "ticket_id": ticket_id,
        "message": f"Ticket créé (#{ticket_id}).",
    }


async def asset_list(
    args: dict[str, Any], *, request: Request = glpi_request
) -> dict[str, Any]:
    system, error = _system(args)
    if error:
        return error
    limit = _limit(args.get("limit"), 50, 200)
    result = await request("GET", "Computer", params={"range": f"0-{limit - 1}"})
    if result.get("error"):
        return result
    computers = result.get("data") if isinstance(result.get("data"), list) else []
    return {
        "success": True,
        "system": system,
        "count": len(computers),
        "assets": [
            {
                "id": computer.get("id"),
                "name": computer.get("name"),
                "serial": computer.get("serial"),
            }
            for computer in computers
            if isinstance(computer, dict)
        ],
    }
