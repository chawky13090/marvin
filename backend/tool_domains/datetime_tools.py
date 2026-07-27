"""Outils déterministes de date, heure et fuseaux IANA."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_ACTIONS = frozenset({"now", "convert", "diff", "add"})
_DELTA_FIELDS = frozenset({"weeks", "days", "hours", "minutes", "seconds"})
_MAX_TIMEZONE_LENGTH = 128
_MAX_DELTA_COMPONENT = 1_000_000
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_timezone(value: object) -> tuple[ZoneInfo | None, str | None]:
    name = str(value or "Europe/Paris").strip()
    if not name or len(name) > _MAX_TIMEZONE_LENGTH:
        return None, "Fuseau horaire IANA invalide."
    try:
        return ZoneInfo(name), None
    except (ZoneInfoNotFoundError, ValueError):
        return None, f"Fuseau horaire IANA inconnu : '{name}'."


def _parse_datetime(value: object, field: str) -> tuple[datetime | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return None, f"Paramètre '{field}' requis."
    if len(text) > 128:
        return None, f"Paramètre '{field}' trop long."
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        return None, f"Format datetime invalide pour '{field}' : {exc}."
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed, None


def _parse_delta(value: object) -> tuple[timedelta | None, str | None]:
    if value in (None, ""):
        value = {}
    if not isinstance(value, Mapping):
        return None, "Le paramètre 'delta' doit être un objet."
    unknown = sorted(set(value) - _DELTA_FIELDS)
    if unknown:
        return None, f"Composante(s) de delta inconnue(s) : {', '.join(unknown)}."
    components: dict[str, int] = {}
    for field in _DELTA_FIELDS:
        raw = value.get(field, 0)
        if isinstance(raw, bool):
            return None, f"Le delta '{field}' doit être un entier."
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            return None, f"Le delta '{field}' doit être un entier."
        if parsed != raw and not (isinstance(raw, str) and str(parsed) == raw.strip()):
            return None, f"Le delta '{field}' doit être un entier."
        if abs(parsed) > _MAX_DELTA_COMPONENT:
            return None, (
                f"Le delta '{field}' dépasse la limite de "
                f"{_MAX_DELTA_COMPONENT:,}.".replace(",", " ")
            )
        components[field] = parsed
    try:
        return timedelta(**components), None
    except OverflowError:
        return None, "Le delta produit une durée hors limites."


async def datetime_info(args: dict[str, Any], *, clock: Clock = _utc_now) -> dict[str, Any]:
    """Retourne, convertit, compare ou décale des dates conscientes du fuseau."""
    action = str(args.get("action") or "now").strip().lower()
    if action not in _ACTIONS:
        return {"error": f"Action inconnue : {action!r}. Utilisez : now, convert, diff, add."}

    target_timezone, error = _load_timezone(args.get("timezone"))
    if error or target_timezone is None:
        return {"error": error or "Fuseau horaire indisponible."}
    timezone_name = target_timezone.key

    if action == "now":
        current = clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current_utc = current.astimezone(timezone.utc)
        local = current_utc.astimezone(target_timezone)
        return {
            "success": True,
            "utc": current_utc.isoformat(),
            "local": local.isoformat(),
            "timezone": timezone_name,
            "weekday": local.strftime("%A"),
            "formatted": local.strftime("%d/%m/%Y %H:%M:%S %Z"),
            "unix": int(current_utc.timestamp()),
        }

    first, error = _parse_datetime(args.get("datetime"), "datetime")
    if error or first is None:
        return {"error": error or "Date invalide."}

    if action == "convert":
        converted = first.astimezone(target_timezone)
        return {
            "success": True,
            "original": first.isoformat(),
            "converted": converted.isoformat(),
            "timezone": timezone_name,
            "formatted": converted.strftime("%d/%m/%Y %H:%M:%S %Z"),
        }

    if action == "diff":
        second, error = _parse_datetime(args.get("datetime2"), "datetime2")
        if error or second is None:
            return {"error": error or "Deuxième date invalide."}
        difference = abs(second - first)
        total_seconds = int(difference.total_seconds())
        return {
            "success": True,
            "diff_seconds": total_seconds,
            "diff_minutes": round(total_seconds / 60, 2),
            "diff_hours": round(total_seconds / 3600, 2),
            "diff_days": difference.days,
            "human": (
                f"{difference.days}j {difference.seconds // 3600}h "
                f"{(difference.seconds % 3600) // 60}min"
            ),
        }

    delta, error = _parse_delta(args.get("delta"))
    if error or delta is None:
        return {"error": error or "Delta invalide."}
    try:
        result = (first + delta).astimezone(target_timezone)
    except OverflowError:
        return {"error": "Le résultat de date dépasse les limites prises en charge."}
    return {
        "success": True,
        "original": first.isoformat(),
        "result": result.isoformat(),
        "formatted": result.strftime("%d/%m/%Y %H:%M:%S %Z"),
    }
