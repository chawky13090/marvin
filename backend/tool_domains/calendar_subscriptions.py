"""Abonnements iCalendar et synchronisation de l'agenda unifié."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urljoin, urlparse, urlunparse

GoogleServiceFactory = Callable[..., Any]
CalendarIdResolver = Callable[[Any], str]

_DEFAULT_COLOR = "#10b981"
_COLOR_RE = __import__("re").compile(r"^#[0-9a-fA-F]{6}$")
_MAX_ICS_BYTES = 10 * 1024 * 1024
_MAX_EVENTS = 5_000
_MAX_REDIRECTS = 3


def load_subscriptions(*, storage: Any = None) -> list[dict[str, Any]]:
    if storage is None:
        import database as storage
    value = storage.get_setting("calendar_subscriptions")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = []
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def save_subscriptions(subscriptions: list[dict[str, Any]], *, storage: Any = None) -> None:
    if storage is None:
        import database as storage
    storage.set_setting("calendar_subscriptions", subscriptions)


def _public(subscription: dict[str, Any]) -> dict[str, Any]:
    result = dict(subscription)
    raw_url = str(result.get("url") or "")
    try:
        parsed = urlparse(raw_url.replace("webcal://", "https://", 1))
        result["url"] = urlunparse((parsed.scheme, parsed.netloc, "/…", "", "", ""))
    except Exception:
        result["url"] = ""
    return result


def parse_ics(data: bytes) -> list[dict[str, Any]]:
    import icalendar
    import recurring_ical_events

    if not isinstance(data, bytes) or len(data) > _MAX_ICS_BYTES:
        raise ValueError("Le flux iCalendar est invalide ou dépasse 10 Mio.")
    calendar = icalendar.Calendar.from_ical(data)
    start = datetime.now() - timedelta(days=30)
    end = datetime.now() + timedelta(days=180)
    try:
        occurrences = recurring_ical_events.of(calendar).between(start, end)
    except Exception:
        occurrences = [component for component in calendar.walk("VEVENT")]

    def format_value(value: Any) -> tuple[str | None, bool]:
        if value is None:
            return None, False
        parsed = value.dt if hasattr(value, "dt") else value
        if isinstance(parsed, datetime):
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone()
            return parsed.strftime("%Y-%m-%d %H:%M"), False
        if isinstance(parsed, date):
            return parsed.strftime("%Y-%m-%d 00:00"), True
        return None, False

    output: list[dict[str, Any]] = []
    for event in occurrences:
        if len(output) >= _MAX_EVENTS:
            break
        try:
            start_at, all_day = format_value(event.get("DTSTART"))
            if not start_at:
                continue
            end_at, _ = format_value(event.get("DTEND"))
            output.append(
                {
                    "title": str(event.get("SUMMARY", "(sans titre)"))[:1024],
                    "location": str(event.get("LOCATION", "") or "")[:1024],
                    "description": str(event.get("DESCRIPTION", "") or "")[:500],
                    "start_at": start_at,
                    "end_at": end_at,
                    "all_day": all_day,
                    "external_id": str(event.get("UID", "") or "")[:1024],
                }
            )
        except Exception:
            continue
    return output


async def _validate_remote_url(url: str) -> str:
    normalized = url.strip()
    if normalized.lower().startswith("webcal://"):
        normalized = "https://" + normalized[9:]
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Le lien iCalendar doit utiliser HTTPS ou HTTP.")
    if parsed.username or parsed.password:
        raise ValueError("Les identifiants intégrés dans une URL iCalendar sont interdits.")
    if parsed.port not in (None, 80, 443):
        raise ValueError("Le port du lien iCalendar doit être 80 ou 443.")
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo, parsed.hostname, parsed.port or 443
        )
    except OSError as exc:
        raise ValueError(f"Hôte iCalendar introuvable : {exc}") from exc
    for entry in addresses:
        address = ipaddress.ip_address(entry[4][0])
        if (
            address.is_loopback
            or address.is_link_local
            or address.is_unspecified
            or address.is_multicast
        ):
            raise ValueError("Le lien iCalendar cible une adresse locale interdite.")
    return normalized


async def fetch_ics(url: str, timeout: int = 25) -> bytes:
    import httpx

    current_url = await _validate_remote_url(url)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=5.0), follow_redirects=False
    ) as client:
        for redirect_count in range(_MAX_REDIRECTS + 1):
            async with client.stream(
                "GET",
                current_url,
                headers={"User-Agent": "Marvin/2 (+calendar-sync)"},
            ) as response:
                if response.is_redirect:
                    if redirect_count >= _MAX_REDIRECTS:
                        raise ValueError(
                            "Le lien iCalendar dépasse la limite de 3 redirections."
                        )
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError(
                            "Le serveur iCalendar renvoie une redirection sans destination."
                        )
                    current_url = await _validate_remote_url(
                        urljoin(current_url, location)
                    )
                    continue
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_ICS_BYTES:
                        raise ValueError("Le flux iCalendar dépasse 10 Mio.")
                return bytes(content)
    raise ValueError("Le flux iCalendar n'a pas pu être téléchargé.")


async def sync_subscription(
    subscription: dict[str, Any],
    *,
    storage: Any = None,
    fetcher: Callable[[str], Any] = fetch_ics,
    parser: Callable[[bytes], list[dict[str, Any]]] = parse_ics,
) -> dict[str, Any]:
    if storage is None:
        import database as storage
    source = f"ics:{subscription.get('id')}"
    try:
        data = await fetcher(str(subscription["url"]))
        events = await asyncio.to_thread(parser, data)
        color = str(subscription.get("color") or _DEFAULT_COLOR)
        for event in events:
            event["color"] = color
        count = storage.replace_external_events(source, events)
        subscription["last_sync"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        subscription["last_error"] = ""
        subscription["count"] = count
        return {"success": True, "count": count}
    except Exception as exc:
        subscription["last_error"] = str(exc)[:200]
        return {"error": str(exc)[:200]}


async def subscribe(
    args: dict[str, Any],
    *,
    storage: Any = None,
    synchronizer: Callable[..., Any] = sync_subscription,
) -> dict[str, Any]:
    if storage is None:
        import database as storage
    url = str(args.get("url") or "").strip()
    name = str(args.get("name") or "").strip() or "Agenda"
    color = str(args.get("color") or _DEFAULT_COLOR).strip()
    if not url:
        return {"error": "Lien iCalendar requis."}
    if len(url) > 4096 or len(name) > 160:
        return {"error": "Lien limité à 4096 caractères et nom à 160."}
    if not _COLOR_RE.fullmatch(color):
        return {"error": "La couleur doit respecter le format #RRGGBB."}
    subscriptions = load_subscriptions(storage=storage)
    if any(str(item.get("url") or "") == url for item in subscriptions):
        return {"error": "Cet agenda est déjà connecté."}
    subscription = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "url": url,
        "color": color,
        "enabled": True,
        "last_sync": "",
        "last_error": "",
        "count": 0,
    }
    result = await synchronizer(subscription, storage=storage)
    subscriptions.append(subscription)
    save_subscriptions(subscriptions, storage=storage)
    public = _public(subscription)
    if result.get("error"):
        return {
            "error": f"Abonnement ajouté mais synchronisation échouée : {result['error']}",
            "subscription": public,
        }
    return {
        "success": True,
        "subscription": public,
        "message": f"Agenda « {name} » connecté : {result.get('count', 0)} événement(s).",
    }


async def list_subscriptions(
    args: dict[str, Any], *, storage: Any = None
) -> dict[str, Any]:
    subscriptions = [_public(item) for item in load_subscriptions(storage=storage)]
    return {
        "success": True,
        "subscriptions": subscriptions,
        "count": len(subscriptions),
    }


async def unsubscribe(
    args: dict[str, Any], *, storage: Any = None
) -> dict[str, Any]:
    if storage is None:
        import database as storage
    key = str(args.get("id") or args.get("name") or "").strip().lower()
    if not key:
        return {"error": "Fournissez l'id ou le nom de l'agenda à déconnecter."}
    subscriptions = load_subscriptions(storage=storage)
    removed = next(
        (
            item
            for item in subscriptions
            if str(item.get("id") or "").lower() == key
            or str(item.get("name") or "").lower() == key
        ),
        None,
    )
    if not removed:
        return {"error": "Agenda introuvable."}
    if not args.get("confirmed"):
        return {
            "requiresConfirmation": True,
            "message": f"Déconnecter l'agenda « {removed.get('name', '')} » "
            "et retirer ses événements importés ?",
        }
    keep = [item for item in subscriptions if item is not removed]
    storage.delete_events_by_source(f"ics:{removed['id']}")
    save_subscriptions(keep, storage=storage)
    return {
        "success": True,
        "message": f"Agenda « {removed.get('name', '')} » déconnecté.",
    }


async def sync_google(
    *,
    storage: Any = None,
    service_factory: GoogleServiceFactory,
    calendar_id_resolver: CalendarIdResolver,
) -> dict[str, Any]:
    if storage is None:
        import database as storage
    try:
        service = service_factory()
    except Exception:
        return {"connected": False, "count": 0}

    def run() -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        response = (
            service.events()
            .list(
                calendarId=calendar_id_resolver("primary"),
                timeMin=(now - timedelta(days=30)).isoformat(),
                timeMax=(now + timedelta(days=180)).isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=500,
            )
            .execute()
        )
        return response.get("items", []) if isinstance(response, dict) else []

    try:
        items = await asyncio.to_thread(run)
    except Exception as exc:
        return {"connected": True, "count": 0, "error": str(exc)[:150]}

    def wall_time(value: Any) -> str | None:
        return str(value).replace("T", " ")[:16] if value else None

    events = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start, end = item.get("start", {}), item.get("end", {})
        events.append(
            {
                "title": str(item.get("summary") or "(sans titre)")[:1024],
                "location": str(item.get("location") or "")[:1024],
                "start_at": wall_time(start.get("dateTime") or start.get("date")),
                "end_at": wall_time(end.get("dateTime") or end.get("date")),
                "all_day": "date" in start,
                "external_id": str(item.get("id") or "")[:1024],
                "color": "#4285f4",
            }
        )
    count = storage.replace_external_events("google", events)
    return {"connected": True, "count": count}


async def sync_all(
    args: dict[str, Any],
    *,
    storage: Any = None,
    synchronizer: Callable[..., Any] = sync_subscription,
    google_synchronizer: Callable[..., Any],
) -> dict[str, Any]:
    if storage is None:
        import database as storage
    subscriptions = load_subscriptions(storage=storage)
    only = str(args.get("id") or "").strip()
    results: list[dict[str, Any]] = []
    total = 0
    succeeded = 0
    for subscription in subscriptions:
        if only and subscription.get("id") != only:
            continue
        if not subscription.get("enabled", True):
            continue
        result = await synchronizer(subscription, storage=storage)
        if result.get("success"):
            total += int(result.get("count") or 0)
            succeeded += 1
        results.append(
            {
                "name": subscription.get("name"),
                "id": subscription.get("id"),
                **result,
            }
        )
    save_subscriptions(subscriptions, storage=storage)
    google = await google_synchronizer(storage=storage)
    if google.get("connected"):
        total += int(google.get("count") or 0)
        google_result = {
            "name": "Google Agenda",
            "id": "google",
            "success": not bool(google.get("error")),
            "count": int(google.get("count") or 0),
        }
        if google.get("error"):
            google_result["error"] = google["error"]
        else:
            succeeded += 1
        results.append(google_result)
    if not subscriptions and not google.get("connected"):
        return {
            "success": True,
            "total_events": 0,
            "results": [],
            "message": "Aucun agenda connecté.",
        }
    return {
        "success": True,
        "synced": succeeded,
        "total_events": total,
        "results": results,
        "message": f"{total} événement(s) synchronisé(s) depuis {succeeded} agenda(s).",
    }
