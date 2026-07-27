"""Domaine météo Open-Meteo avec transport et cache injectables."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


HttpClientFactory = Callable[[], Any]
CacheGet = Callable[[Any], Any]
CacheSet = Callable[[Any, Any], None]
NetError = Callable[[Exception, str], dict[str, Any]]


def _missing_client() -> Any:
    raise RuntimeError("Client HTTP météo non configuré.")


def _empty_cache(_: Any) -> Any:
    return None


def _ignore_cache(_: Any, __: Any) -> None:
    return None


def _default_net_error(exc: Exception, what: str) -> dict[str, Any]:
    return {"error": f"{what} : {exc}"}


_get_http_client: HttpClientFactory = _missing_client
_cache_get: CacheGet = _empty_cache
_cache_set: CacheSet = _ignore_cache
_net_error: NetError = _default_net_error


def configure(
    *,
    get_http_client: HttpClientFactory,
    cache_get: CacheGet,
    cache_set: CacheSet,
    net_error: NetError,
) -> None:
    global _get_http_client, _cache_get, _cache_set, _net_error
    _get_http_client = get_http_client
    _cache_get = cache_get
    _cache_set = cache_set
    _net_error = net_error


_WMO = {
    0: "Ciel dégagé",
    1: "Principalement dégagé",
    2: "Partiellement nuageux",
    3: "Couvert",
    45: "Brouillard",
    48: "Brouillard givrant",
    51: "Bruine légère",
    53: "Bruine modérée",
    55: "Bruine dense",
    56: "Bruine verglaçante légère",
    57: "Bruine verglaçante dense",
    61: "Pluie légère",
    63: "Pluie modérée",
    65: "Forte pluie",
    66: "Pluie verglaçante légère",
    67: "Forte pluie verglaçante",
    71: "Neige légère",
    73: "Neige modérée",
    75: "Forte neige",
    77: "Grains de neige",
    80: "Averses légères",
    81: "Averses modérées",
    82: "Averses violentes",
    85: "Averses de neige",
    86: "Fortes averses de neige",
    95: "Orage",
    96: "Orage avec grêle",
    99: "Orage fort avec grêle",
}


def _condition(value: object) -> str:
    try:
        code = int(value)
    except (TypeError, ValueError):
        return "Condition inconnue"
    return _WMO.get(code, f"Code WMO {code}")


def _validate_request(args: dict[str, Any]) -> tuple[str, str, int, str | None]:
    city = str(args.get("city") or "Paris").strip()
    country = str(args.get("country") or "FR").strip().upper()
    if not city or len(city) > 160:
        return city, country, 1, "Ville requise et limitée à 160 caractères."
    if country and (len(country) != 2 or not country.isascii() or not country.isalpha()):
        return city, country, 1, "Le pays doit être un code ISO 3166-1 alpha-2."
    try:
        days = int(args.get("days", 1))
    except (TypeError, ValueError):
        return city, country, 1, "Le nombre de jours doit être un entier entre 1 et 7."
    if isinstance(args.get("days"), bool) or not 1 <= days <= 7:
        return city, country, days, "Le nombre de jours doit être compris entre 1 et 7."
    return city, country, days, None


def _location(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        latitude = float(value["latitude"])
        longitude = float(value["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return {
        "name": str(value.get("name") or "").strip(),
        "country": str(value.get("country") or "").strip(),
        "country_code": str(value.get("country_code") or "").strip().upper(),
        "latitude": latitude,
        "longitude": longitude,
        "timezone": str(value.get("timezone") or "").strip(),
    }


async def _resolve_location(city: str, country: str) -> tuple[dict[str, Any] | None, dict | None]:
    cache_key = ("weather-geocode", city.casefold(), country)
    cached = _cache_get(cache_key)
    if isinstance(cached, Mapping):
        normalized = _location(cached)
        if normalized:
            return normalized, None
    params: dict[str, Any] = {
        "name": city,
        "count": 5,
        "language": "fr",
        "format": "json",
    }
    if country:
        params["countryCode"] = country
    try:
        response = await _get_http_client().get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return None, _net_error(exc, "Géocodage Open-Meteo")
    results = payload.get("results") if isinstance(payload, Mapping) else None
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        results = []
    location = next(
        (
            normalized
            for candidate in results[:5]
            if (normalized := _location(candidate)) is not None
            and (not country or normalized["country_code"] == country)
        ),
        None,
    )
    if location is None:
        return None, {"error": f"Ville '{city}' non trouvée pour le pays '{country}'."}
    _cache_set(cache_key, location)
    return location, None


def _at(values: object, index: int) -> Any:
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        return values[index] if index < len(values) else None
    return None


async def weather(args: dict[str, Any]) -> dict[str, Any]:
    """Retourne les conditions actuelles et jusqu'à sept prévisions journalières."""
    city, country, days, error = _validate_request(args)
    if error:
        return {"error": error}
    location, failure = await _resolve_location(city, country)
    if failure or location is None:
        return failure or {"error": "Localisation indisponible."}
    try:
        response = await _get_http_client().get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "current": (
                    "temperature_2m,relative_humidity_2m,apparent_temperature,"
                    "precipitation,wind_speed_10m,weather_code"
                ),
                "daily": (
                    "temperature_2m_max,temperature_2m_min,"
                    "precipitation_sum,weather_code"
                ),
                "forecast_days": days,
                "timezone": "auto",
            },
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return _net_error(exc, "Prévisions Open-Meteo")
    if not isinstance(payload, Mapping):
        return {"error": "Réponse Open-Meteo invalide : objet JSON attendu."}
    current = payload.get("current")
    daily = payload.get("daily")
    if not isinstance(current, Mapping) or not isinstance(daily, Mapping):
        return {"error": "Réponse Open-Meteo incomplète : current/daily absents."}
    dates = daily.get("time")
    if not isinstance(dates, Sequence) or isinstance(dates, (str, bytes)):
        return {"error": "Réponse Open-Meteo invalide : dates journalières absentes."}

    forecasts = [
        {
            "date": dates[index],
            "condition": _condition(_at(daily.get("weather_code"), index)),
            "temp_max": _at(daily.get("temperature_2m_max"), index),
            "temp_min": _at(daily.get("temperature_2m_min"), index),
            "precipitation": _at(daily.get("precipitation_sum"), index),
        }
        for index in range(min(len(dates), days))
    ]
    label = ", ".join(part for part in (location["name"] or city, location["country"]) if part)
    return {
        "success": True,
        "current": {
            "city": label,
            "condition": _condition(current.get("weather_code")),
            "temperature": current.get("temperature_2m"),
            "feels_like": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "wind_speed": current.get("wind_speed_10m"),
            "precipitation": current.get("precipitation"),
        },
        "forecasts": forecasts,
        "timezone": payload.get("timezone") or location["timezone"] or None,
        "units": {
            "current": dict(payload.get("current_units") or {}),
            "daily": dict(payload.get("daily_units") or {}),
        },
        "source": "Open-Meteo (open-meteo.com)",
    }
