"""Google Calendar : authentification, normalisation et opérations distantes."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ServiceFactory = Callable[..., Any]

SERVICE_ACCOUNT_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "google_service_account.json"
)
_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
_TIMEZONE = "Europe/Paris"


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def service_account_email() -> str | None:
    try:
        payload = json.loads(SERVICE_ACCOUNT_PATH.read_text(encoding="utf-8"))
        email = payload.get("client_email")
        return str(email) if email else None
    except (OSError, ValueError, TypeError):
        return None


def resolve_calendar_id(requested: Any) -> str:
    import database

    calendar_id = str(requested or "primary").strip() or "primary"
    if calendar_id == "primary" and SERVICE_ACCOUNT_PATH.is_file():
        configured = database.get_setting("google_calendar_id")
        if configured:
            return str(configured).strip()
    return calendar_id


def normalize_datetime(value: Any) -> str:
    text = str(value or "").strip().replace(" ", "T")
    if not text or "T" not in text:
        return text
    try:
        return datetime.fromisoformat(text).isoformat(timespec="seconds")
    except ValueError:
        return text


def is_ready() -> bool:
    import credentials_manager
    import database

    try:
        if SERVICE_ACCOUNT_PATH.is_file() and database.get_setting(
            "google_calendar_id"
        ):
            return True
        if credentials_manager.get_credential(
            "google_access_token"
        ) or credentials_manager.get_credential("google_refresh_token"):
            return True
        with database.db() as connection:
            row = connection.execute(
                "SELECT access_token, refresh_token FROM oauth_tokens "
                "WHERE provider='google'"
            ).fetchone()
        return bool(row and (row["access_token"] or row["refresh_token"]))
    except Exception:
        return False


def build_service(prefer_oauth: bool = False) -> Any:
    import credentials_manager
    import database
    from google.oauth2.credentials import Credentials
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    if SERVICE_ACCOUNT_PATH.is_file() and not prefer_oauth:
        credentials = service_account.Credentials.from_service_account_file(
            str(SERVICE_ACCOUNT_PATH), scopes=[_CALENDAR_SCOPE]
        )
        return build(
            "calendar", "v3", credentials=credentials, cache_discovery=False
        )

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
        scopes=[_CALENDAR_SCOPE],
    )
    return build(
        "calendar", "v3", credentials=credentials, cache_discovery=False
    )


def _parse_start(value: Any) -> tuple[str, bool, datetime | date]:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Paramètre 'start' requis.")
    normalized = text.replace(" ", "T")
    try:
        if "T" in normalized:
            parsed: datetime | date = datetime.fromisoformat(normalized)
            return normalize_datetime(normalized), False, parsed
        parsed = date.fromisoformat(normalized)
        return normalized, True, parsed
    except ValueError as exc:
        raise ValueError(
            f"Date 'start' invalide : « {text} ». "
            "Format attendu : YYYY-MM-DDTHH:MM:SS ou YYYY-MM-DD."
        ) from exc


def _parse_end(value: Any, *, all_day: bool) -> tuple[str, datetime | date]:
    text = str(value or "").strip().replace(" ", "T")
    try:
        if all_day:
            return text, date.fromisoformat(text)
        normalized = normalize_datetime(text)
        return normalized, datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("La date de fin est invalide ou incompatible avec le début.") from exc


async def list_events(
    args: dict[str, Any], *, service_factory: ServiceFactory = build_service
) -> dict[str, Any]:
    from dateutil import parser as date_parser

    calendar_id = resolve_calendar_id(args.get("calendar_id"))
    days = _bounded_int(args.get("days"), 7, 1, 90)
    maximum = _bounded_int(args.get("max_results"), 20, 1, 50)
    now = datetime.now(timezone.utc)
    raw_min = str(args.get("time_min") or "").strip()
    try:
        start_at = date_parser.parse(raw_min).astimezone(timezone.utc) if raw_min else now
    except (ValueError, TypeError, OverflowError):
        return {"error": "time_min doit être une date ISO 8601 valide."}
    end_at = start_at + timedelta(days=days)

    def fetch(service: Any) -> list[dict[str, Any]]:
        response = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=start_at.isoformat(),
                timeMax=end_at.isoformat(),
                maxResults=maximum,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        items = response.get("items", []) if isinstance(response, dict) else []
        return [
            {
                "id": event.get("id", ""),
                "title": event.get("summary", "(Sans titre)"),
                "start": event.get("start", {}).get("dateTime")
                or event.get("start", {}).get("date", ""),
                "end": event.get("end", {}).get("dateTime")
                or event.get("end", {}).get("date", ""),
                "location": event.get("location", ""),
                "description": str(event.get("description") or "")[:300],
                "organizer": event.get("organizer", {}).get("email", ""),
                "status": event.get("status", ""),
                "colorId": event.get("colorId", ""),
                "link": event.get("htmlLink", ""),
            }
            for event in items
            if isinstance(event, dict)
        ]

    def run() -> list[dict[str, Any]]:
        try:
            return fetch(service_factory())
        except Exception as exc:
            if getattr(getattr(exc, "resp", None), "status", None) != 404:
                raise
            return fetch(service_factory(prefer_oauth=True))

    try:
        events = await asyncio.to_thread(run)
        return {
            "success": True,
            "calendar_id": calendar_id,
            "period_days": days,
            "count": len(events),
            "events": events,
        }
    except Exception as exc:
        return {"error": f"Google Calendar : {str(exc)[:300]}"}


async def create_event(
    args: dict[str, Any], *, service_factory: ServiceFactory = build_service
) -> dict[str, Any]:
    title = str(args.get("title") or "").strip()
    if not title:
        return {"error": "Paramètre 'title' requis."}
    if len(title) > 1024:
        return {"error": "Le titre est limité à 1024 caractères."}
    try:
        start, all_day, parsed_start = _parse_start(args.get("start"))
        if args.get("end") not in (None, ""):
            end, parsed_end = _parse_end(args.get("end"), all_day=all_day)
        elif all_day:
            parsed_end = parsed_start + timedelta(days=1)
            end = parsed_end.isoformat()
        else:
            parsed_end = parsed_start + timedelta(hours=1)
            end = parsed_end.isoformat(timespec="seconds")
        if parsed_end <= parsed_start:
            return {"error": "La fin de l'événement doit être postérieure au début."}
    except ValueError as exc:
        return {"error": str(exc)}
    calendar_id = resolve_calendar_id(args.get("calendar_id"))
    location = str(args.get("location") or "")[:1024]
    description = str(args.get("description") or "")[:20_000]
    reminder = args.get("reminder_minutes")
    reminder_minutes: int | None = None
    if reminder not in (None, ""):
        try:
            reminder_minutes = int(reminder)
        except (TypeError, ValueError):
            return {"error": "reminder_minutes doit être un entier."}
        if not 0 <= reminder_minutes <= 40_320:
            return {"error": "reminder_minutes doit être compris entre 0 et 40320."}

    def run() -> dict[str, Any]:
        body: dict[str, Any] = {
            "summary": title,
            "start": {"date": start}
            if all_day
            else {"dateTime": start, "timeZone": _TIMEZONE},
            "end": {"date": end}
            if all_day
            else {"dateTime": end, "timeZone": _TIMEZONE},
        }
        if location:
            body["location"] = location
        if description:
            body["description"] = description
        if reminder_minutes is not None:
            body["reminders"] = {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": reminder_minutes}],
            }
        created = (
            service_factory()
            .events()
            .insert(calendarId=calendar_id, body=body)
            .execute()
        )
        return {
            "success": True,
            "message": f"Événement créé : « {title} »",
            "id": created.get("id", ""),
            "event_id": created.get("id", ""),
            "summary": created.get("summary", title),
            "start": created.get("start", body["start"]),
            "end": created.get("end", body["end"]),
            "location": created.get("location", location),
            "description": created.get("description", description),
            "htmlLink": created.get("htmlLink", ""),
        }

    try:
        return await asyncio.to_thread(run)
    except Exception as exc:
        return {"error": f"Google Calendar : {str(exc)[:300]}"}


async def delete_event(
    args: dict[str, Any], *, service_factory: ServiceFactory = build_service
) -> dict[str, Any]:
    event_id = str(args.get("event_id") or "").strip()
    if not event_id or len(event_id) > 1024:
        return {"error": "Paramètre 'event_id' requis et limité à 1024 caractères."}
    if not args.get("confirmed"):
        return {
            "requiresConfirmation": True,
            "message": f"Supprimer l'événement Google Calendar ID « {event_id} » ? "
            "Cette action est irréversible.",
        }
    calendar_id = resolve_calendar_id(args.get("calendar_id"))

    def run() -> dict[str, Any]:
        (
            service_factory()
            .events()
            .delete(calendarId=calendar_id, eventId=event_id)
            .execute()
        )
        return {
            "success": True,
            "message": f"Événement {event_id} supprimé du calendrier.",
        }

    try:
        return await asyncio.to_thread(run)
    except Exception as exc:
        return {"error": f"Google Calendar : {str(exc)[:300]}"}


def _duration(existing: dict[str, Any]) -> timedelta | None:
    start = existing.get("start", {})
    end = existing.get("end", {})
    try:
        if start.get("dateTime") and end.get("dateTime"):
            return datetime.fromisoformat(
                str(end["dateTime"]).replace("Z", "+00:00")
            ) - datetime.fromisoformat(str(start["dateTime"]).replace("Z", "+00:00"))
        if start.get("date") and end.get("date"):
            return datetime.fromisoformat(str(end["date"])) - datetime.fromisoformat(
                str(start["date"])
            )
    except (ValueError, TypeError):
        return None
    return None


async def update_event(
    args: dict[str, Any], *, service_factory: ServiceFactory = build_service
) -> dict[str, Any]:
    event_id = str(args.get("event_id") or "").strip()
    if not event_id or len(event_id) > 1024:
        return {"error": "Paramètre 'event_id' requis et limité à 1024 caractères."}
    calendar_id = resolve_calendar_id(args.get("calendar_id"))

    def run() -> dict[str, Any]:
        service = service_factory()
        existing = (
            service.events()
            .get(calendarId=calendar_id, eventId=event_id)
            .execute()
        )
        duration = _duration(existing)
        if args.get("title") is not None:
            existing["summary"] = str(args["title"])[:1024]
        if args.get("description") is not None:
            existing["description"] = str(args["description"])[:20_000]
        if args.get("location") is not None:
            existing["location"] = str(args["location"])[:1024]
        if args.get("start") is not None:
            start, all_day, parsed_start = _parse_start(args["start"])
            existing["start"] = (
                {"date": start}
                if all_day
                else {"dateTime": start, "timeZone": _TIMEZONE}
            )
            if args.get("end") is None and duration and duration.total_seconds() > 0:
                shifted = parsed_start + duration
                existing["end"] = (
                    {"date": shifted.isoformat()}
                    if all_day
                    else {
                        "dateTime": shifted.isoformat(timespec="seconds"),
                        "timeZone": _TIMEZONE,
                    }
                )
        if args.get("end") is not None:
            start_is_all_day = "date" in existing.get("start", {})
            end, _ = _parse_end(args["end"], all_day=start_is_all_day)
            existing["end"] = (
                {"date": end}
                if start_is_all_day
                else {"dateTime": end, "timeZone": _TIMEZONE}
            )
        updated = (
            service.events()
            .update(calendarId=calendar_id, eventId=event_id, body=existing)
            .execute()
        )
        return {
            "id": updated.get("id"),
            "title": updated.get("summary", ""),
            "start": updated.get("start", {}),
            "end": updated.get("end", {}),
            "description": updated.get("description", ""),
            "location": updated.get("location", ""),
            "colorId": updated.get("colorId"),
            "success": True,
            "message": f"Événement « {updated.get('summary', '')} » mis à jour.",
        }

    try:
        return await asyncio.to_thread(run)
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": f"Google Calendar : {str(exc)[:300]}"}
