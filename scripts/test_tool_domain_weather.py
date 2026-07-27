"""Régressions du domaine météo Open-Meteo."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from agent_safety import validator_for
from tool_domains import weather


class Response:
    def __init__(self, payload: Any, *, failure: Exception | None = None):
        self.payload = payload
        self.failure = failure

    def raise_for_status(self) -> None:
        if self.failure:
            raise self.failure

    def json(self) -> Any:
        return self.payload


class Client:
    def __init__(self, responses: list[Response]):
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, url: str, *, params: dict[str, Any]) -> Response:
        self.calls.append((url, params))
        if not self.responses:
            raise AssertionError("Appel HTTP inattendu")
        return self.responses.pop(0)


def forecast_payload() -> dict[str, Any]:
    return {
        "timezone": "Europe/Paris",
        "current": {
            "temperature_2m": 21.5,
            "relative_humidity_2m": 54,
            "apparent_temperature": 21.0,
            "precipitation": 0.0,
            "wind_speed_10m": 8.2,
            "weather_code": 2,
        },
        "current_units": {"temperature_2m": "°C", "wind_speed_10m": "km/h"},
        "daily": {
            "time": ["2026-07-28", "2026-07-29"],
            "temperature_2m_max": [24.0, 25.0],
            "temperature_2m_min": [14.0, 15.0],
            "precipitation_sum": [0.0, 1.2],
            "weather_code": [2, 61],
        },
        "daily_units": {"temperature_2m_max": "°C", "precipitation_sum": "mm"},
    }


async def run_domain() -> None:
    cache: dict[Any, Any] = {}
    client = Client([
        Response({
            "results": [{
                "name": "Paris",
                "country": "France",
                "country_code": "FR",
                "latitude": 48.8567,
                "longitude": 2.3508,
                "timezone": "Europe/Paris",
            }]
        }),
        Response(forecast_payload()),
        Response(forecast_payload()),
    ])
    weather.configure(
        get_http_client=lambda: client,
        cache_get=cache.get,
        cache_set=cache.__setitem__,
        net_error=lambda exc, what: {"error": f"{what}: {exc}", "offline": True},
    )
    first = await weather.weather({"city": "Paris", "country": "fr", "days": 2})
    assert first["success"] is True
    assert first["current"]["condition"] == "Partiellement nuageux"
    assert first["forecasts"][1]["condition"] == "Pluie légère"
    assert first["timezone"] == "Europe/Paris"
    assert first["units"]["daily"]["precipitation_sum"] == "mm"
    assert client.calls[0][1]["countryCode"] == "FR"
    assert client.calls[1][1]["forecast_days"] == 2

    second = await weather.weather({"city": "PARIS", "country": "FR", "days": 1})
    assert second["success"] is True
    assert len(client.calls) == 3
    assert "forecast" in client.calls[2][0]

    assert "ISO" in (await weather.weather({"city": "Paris", "country": "France"}))["error"]
    assert "1 et 7" in (await weather.weather({"city": "Paris", "days": 8}))["error"]

    missing_client = Client([Response({"results": []})])
    weather.configure(
        get_http_client=lambda: missing_client,
        cache_get=lambda _: None,
        cache_set=lambda *_: None,
        net_error=lambda exc, what: {"error": f"{what}: {exc}"},
    )
    missing = await weather.weather({"city": "VilleInconnue", "country": "FR"})
    assert "non trouvée" in missing["error"]

    broken_client = Client([Response({}, failure=RuntimeError("réseau coupé"))])
    weather.configure(
        get_http_client=lambda: broken_client,
        cache_get=lambda _: None,
        cache_set=lambda *_: None,
        net_error=lambda exc, what: {"error": f"{what}: {exc}", "offline": True},
    )
    broken = await weather.weather({"city": "Paris", "country": "FR"})
    assert broken["offline"] is True
    assert "réseau coupé" in broken["error"]


def main() -> int:
    assert tools.execute_weather is weather.weather
    assert tools.TOOLS_REGISTRY["weather"] is weather.weather
    asyncio.run(run_domain())
    validator = validator_for(tools.TOOLS_SPEC)
    assert "inférieur ou égal" in (
        validator("weather", {"city": "Paris", "days": 8}) or ""
    )
    print("Weather Domain OK - validation, pays, cache, projection, erreurs et facade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
