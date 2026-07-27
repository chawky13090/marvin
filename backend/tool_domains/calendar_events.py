"""Événements de l'agenda unifié, avec routage Google explicite et sûr."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable

AsyncTool = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
NaturalGenerator = Callable[..., Awaitable[str]]

_MAX_TITLE = 1024
_MAX_TEXT = 20_000
_MAX_LIST = 500
_MAX_REMINDER_MINUTES = 28 * 24 * 60


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def period_range(period: str) -> tuple[str | None, str | None, str]:
    """Retourne des bornes locales stables pour les périodes exposées au LLM."""
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    normalized = (period or "upcoming").lower().strip()
    if normalized in {"today", "jour", "aujourd'hui", "aujourdhui"}:
        return (
            today.strftime("%Y-%m-%d 00:00"),
            today.strftime("%Y-%m-%d 23:59"),
            "aujourd'hui",
        )
    if normalized in {"tomorrow", "demain"}:
        target = today + timedelta(days=1)
        return (
            target.strftime("%Y-%m-%d 00:00"),
            target.strftime("%Y-%m-%d 23:59"),
            "demain",
        )
    if normalized in {"week", "semaine", "7days"}:
        return (
            today.strftime("%Y-%m-%d 00:00"),
            (today + timedelta(days=7)).strftime("%Y-%m-%d 23:59"),
            "cette semaine",
        )
    if normalized in {"month", "mois", "30days"}:
        return (
            today.strftime("%Y-%m-%d 00:00"),
            (today + timedelta(days=31)).strftime("%Y-%m-%d 23:59"),
            "ce mois-ci",
        )
    if normalized in {"all", "tout"}:
        return None, None, "tous"
    return (
        now.strftime("%Y-%m-%d %H:%M"),
        (today + timedelta(days=30)).strftime("%Y-%m-%d 23:59"),
        "à venir",
    )


def _bounded_text(value: Any, *, name: str, maximum: int) -> str:
    text = str(value or "").strip()
    if len(text) > maximum:
        raise ValueError(f"{name} dépasse la limite de {maximum} caractères.")
    return text


def _normalize_datetime(value: Any, *, name: str, required: bool = False) -> str | None:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValueError(f"{name} est requis.")
        return None
    candidate = text.replace("T", " ")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{name} doit respecter YYYY-MM-DD HH:MM.") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%d %H:%M")


def _normalize_event_fields(
    *,
    title: Any,
    start_at: Any,
    end_at: Any,
    location: Any,
    description: Any,
    reminder: Any,
) -> dict[str, Any]:
    normalized_title = _bounded_text(title, name="Le titre", maximum=_MAX_TITLE)
    if not normalized_title:
        raise ValueError("Titre de l'événement requis.")
    start = _normalize_datetime(start_at, name="La date de début", required=True)
    end = _normalize_datetime(end_at, name="La date de fin")
    if end and end <= start:
        raise ValueError("La date de fin doit être postérieure à la date de début.")
    if reminder in (None, ""):
        reminder_minutes = None
    else:
        try:
            reminder_minutes = int(reminder)
        except (TypeError, ValueError) as exc:
            raise ValueError("Le rappel doit être un nombre entier de minutes.") from exc
        if not 0 <= reminder_minutes <= _MAX_REMINDER_MINUTES:
            raise ValueError("Le rappel doit être compris entre 0 et 40320 minutes.")
    return {
        "title": normalized_title,
        "start_at": start,
        "end_at": end,
        "location": _bounded_text(location, name="Le lieu", maximum=2048),
        "description": _bounded_text(
            description, name="La description", maximum=_MAX_TEXT
        ),
        "reminder_minutes": reminder_minutes,
    }


async def parse_natural_when(
    text: str,
    *,
    generator: NaturalGenerator,
    model: str | None = None,
    weekdays: list[str] | tuple[str, ...],
    months: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    request = _bounded_text(text, name="La demande", maximum=4000)
    if not request:
        raise ValueError("La demande de rendez-vous est vide.")
    today = date.today()
    today_fr = f"{weekdays[today.weekday()]} {today.day} {months[today.month - 1]} {today.year}"
    prompt = (
        f"Nous sommes le {today_fr} (date ISO {today.isoformat()}). "
        "Analyse cette demande de rendez-vous et renvoie UNIQUEMENT un objet JSON valide :\n"
        '{"title":"...","start_at":"YYYY-MM-DD HH:MM","end_at":'
        '"YYYY-MM-DD HH:MM ou null","all_day":false,"location":""}\n'
        "Si aucune heure n'est précisée, utilise 09:00. Le titre ne contient pas la date.\n"
        f"Demande : {request}"
    )
    raw = await generator(prompt, model=model, timeout=120)
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        raise ValueError("Le modèle n'a pas retourné de date structurée.")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError("Le modèle a retourné un JSON de date invalide.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("La date interprétée doit être un objet JSON.")
    return parsed


async def create_event(
    args: dict[str, Any],
    *,
    storage: Any,
    natural_parser: Callable[..., Awaitable[dict[str, Any]]],
    google_ready: Callable[[], bool],
    google_create: AsyncTool,
    google_sync: Callable[[], Awaitable[Any]],
) -> dict[str, Any]:
    title = str(args.get("title") or "").strip()
    start_at = str(args.get("start_at") or "").strip()
    natural = str(args.get("natural") or args.get("text") or "").strip()
    end_at: Any = args.get("end_at")
    all_day = bool(args.get("all_day", False))
    location: Any = args.get("location")
    if not start_at and (natural or title):
        try:
            parsed = await natural_parser(natural or title, model=args.get("model"))
            title = title or str(parsed.get("title") or "").strip()
            start_at = str(parsed.get("start_at") or "").strip()
            end_at = end_at or parsed.get("end_at")
            all_day = all_day or bool(parsed.get("all_day"))
            location = location or parsed.get("location")
        except Exception as exc:
            return {
                "error": (
                    f"Date non comprise : {exc}. "
                    "Précisez par exemple « réunion 2026-08-20 14:00 »."
                )
            }
    try:
        event = _normalize_event_fields(
            title=title,
            start_at=start_at,
            end_at=end_at,
            location=location,
            description=args.get("description"),
            reminder=args.get("reminder_minutes"),
        )
    except ValueError as exc:
        return {"error": str(exc)}

    if google_ready() and not args.get("local_only"):
        google_args = {
            "title": event["title"],
            "start": event["start_at"] if all_day else event["start_at"].replace(" ", "T"),
            "end": (
                event["end_at"]
                if all_day
                else (event["end_at"] or "").replace(" ", "T")
            ),
            "location": event["location"],
            "description": event["description"],
            "reminder_minutes": event["reminder_minutes"],
        }
        try:
            result = await google_create(google_args)
        except Exception as exc:
            result = {"error": str(exc)}
        if not result.get("success"):
            return {
                "error": (
                    "Google Agenda est connecté mais la création a échoué : "
                    f"{result.get('error') or result.get('message') or 'erreur inconnue'}. "
                    "Aucun doublon local n'a été créé. Utilisez local_only=true uniquement "
                    "si vous souhaitez explicitement enregistrer cet événement en local."
                ),
                "target": "google",
                "local_fallback_available": True,
            }
        try:
            await google_sync()
        except Exception:
            pass
        return {
            "success": True,
            "event": result,
            "target": "google",
            "message": (
                f"Créé sur Google Agenda : « {event['title']} » le {event['start_at']}."
            ),
        }

    created = storage.create_event(
        title=event["title"],
        start_at=event["start_at"],
        end_at=event["end_at"],
        description=event["description"],
        location=event["location"],
        all_day=all_day,
        reminder_minutes=event["reminder_minutes"],
        tags=args.get("tags"),
    )
    return {
        "success": True,
        "event": created,
        "target": "local",
        "message": f"Événement créé : « {event['title']} » le {event['start_at']}.",
    }


async def list_events(args: dict[str, Any], *, storage: Any) -> dict[str, Any]:
    start = str(args.get("start") or "").strip() or None
    end = str(args.get("end") or "").strip() or None
    label = None
    try:
        if start:
            start = _normalize_datetime(start, name="La borne de début", required=True)
        if end:
            end = _normalize_datetime(end, name="La borne de fin", required=True)
        if start and end and end < start:
            raise ValueError("La borne de fin doit être postérieure à la borne de début.")
        limit = int(args.get("limit", 200))
        if not 1 <= limit <= _MAX_LIST:
            raise ValueError("La limite doit être comprise entre 1 et 500.")
    except (TypeError, ValueError) as exc:
        return {"error": str(exc)}
    if not start and not end:
        start, end, label = period_range(str(args.get("period") or "upcoming"))
    events = storage.list_events(start=start, end=end, limit=limit)
    return {
        "success": True,
        "events": events,
        "count": len(events),
        "period": label or "personnalisé",
        "message": f"{len(events)} événement(s).",
    }


async def update_event(
    args: dict[str, Any],
    *,
    storage: Any,
    google_update: AsyncTool,
    google_sync: Callable[[], Awaitable[Any]],
) -> dict[str, Any]:
    event_id = str(args.get("id") or args.get("event_id") or "").strip()
    if not event_id:
        return {"error": "id de l'événement requis."}
    try:
        current = storage.get_event(event_id)
    except Exception:
        current = None
    if not current:
        return {"error": "Événement introuvable."}
    allowed = (
        "title", "start_at", "end_at", "location", "description",
        "reminder_minutes", "all_day", "color",
    )
    updates = {key: args[key] for key in allowed if key in args and args[key] is not None}
    if not updates:
        return {"error": "Aucun champ à modifier."}
    if "start_at" in updates and "end_at" not in updates:
        try:
            previous_start = datetime.fromisoformat(
                str(current.get("start_at") or "").replace("T", " ")
            )
            previous_end = datetime.fromisoformat(
                str(current.get("end_at") or "").replace("T", " ")
            )
            next_start = datetime.fromisoformat(
                str(updates["start_at"]).replace("T", " ")
            )
            updates["end_at"] = next_start + (previous_end - previous_start)
        except (TypeError, ValueError):
            # Sans durée historique exploitable, le domaine distant appliquera sa durée
            # par défaut; aucune fin arbitraire n'est inventée ici.
            pass
    try:
        title = updates.get("title", current.get("title"))
        start = updates.get("start_at", current.get("start_at"))
        end = updates.get("end_at", current.get("end_at"))
        normalized = _normalize_event_fields(
            title=title,
            start_at=start,
            end_at=end,
            location=updates.get("location", current.get("location")),
            description=updates.get("description", current.get("description")),
            reminder=updates.get("reminder_minutes", current.get("reminder_minutes")),
        )
    except ValueError as exc:
        return {"error": str(exc)}
    for key in ("title", "start_at", "end_at", "location", "description", "reminder_minutes"):
        if key in updates:
            updates[key] = normalized[key]
    if "start_at" in updates:
        updates["reminded"] = False

    if current.get("source") == "google" and current.get("external_id"):
        google_args: dict[str, Any] = {"event_id": current["external_id"]}
        for local, remote in (
            ("title", "title"),
            ("description", "description"),
            ("location", "location"),
        ):
            if local in updates:
                google_args[remote] = updates[local]
        if "start_at" in updates:
            google_args["start"] = normalized["start_at"].replace(" ", "T")
        if "end_at" in updates:
            google_args["end"] = (normalized["end_at"] or "").replace(" ", "T")
        try:
            result = await google_update(google_args)
        except Exception as exc:
            result = {"error": str(exc)}
        if not result.get("success"):
            return {
                "error": (
                    "La mise à jour Google a échoué; la copie locale n'a pas été "
                    f"modifiée : {result.get('error') or 'erreur inconnue'}."
                ),
                "target": "google",
            }
        try:
            await google_sync()
        except Exception:
            pass
        return {
            "success": True,
            "event": result,
            "target": "google",
            "message": "Événement mis à jour sur Google Agenda.",
        }

    updated = storage.update_event(event_id, updates)
    return {
        "success": True,
        "event": updated,
        "target": "local",
        "message": f"Événement mis à jour : « {updated.get('title')} ».",
    }


async def delete_event(
    args: dict[str, Any],
    *,
    storage: Any,
    google_delete: AsyncTool,
    google_sync: Callable[[], Awaitable[Any]],
) -> dict[str, Any]:
    event_id = str(args.get("id") or args.get("event_id") or "").strip()
    title = str(args.get("title") or "").strip().casefold()
    found = None
    if not event_id and title:
        matches = [
            event
            for event in storage.list_events(limit=_MAX_LIST)
            if title in str(event.get("title") or "").casefold()
        ]
        if len(matches) > 1:
            return {
                "error": "Plusieurs événements correspondent; choisissez un identifiant.",
                "ambiguous": True,
                "candidates": [
                    {
                        "id": event.get("id"),
                        "title": event.get("title"),
                        "start_at": event.get("start_at"),
                    }
                    for event in matches[:20]
                ],
            }
        if matches:
            found = matches[0]
            event_id = str(found.get("id") or "")
    if not event_id:
        return {"error": "Aucun événement correspondant (id ou titre requis)."}
    if found is None:
        try:
            found = storage.get_event(event_id)
        except Exception:
            found = None
    if not found:
        return {"error": "Événement introuvable."}
    if not args.get("confirmed"):
        return {
            "requiresConfirmation": True,
            "message": (
                f"Supprimer définitivement « {found.get('title')} » du "
                f"{str(found.get('start_at') or '')[:16]} ?"
            ),
        }
    if found.get("source") == "google" and found.get("external_id"):
        try:
            result = await google_delete(
                {"event_id": found["external_id"], "confirmed": True}
            )
        except Exception as exc:
            result = {"error": str(exc)}
        if not result.get("success"):
            return {
                "error": (
                    "La suppression Google a échoué; la copie locale est conservée : "
                    f"{result.get('error') or 'erreur inconnue'}."
                ),
                "target": "google",
            }
        storage.delete_event(event_id)
        try:
            await google_sync()
        except Exception:
            pass
        return {
            "success": True,
            "target": "google",
            "message": "Événement supprimé de Google Agenda.",
        }
    storage.delete_event(event_id)
    return {
        "success": True,
        "target": "local",
        "message": "Événement supprimé.",
    }
