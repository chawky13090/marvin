"""Contrat HTTP borné de l'unique propriétaire des réglages Marvin."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from api import settings


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(settings.router)
    return app


async def _request(method: str, url: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


async def _checks() -> None:
    with patch.object(settings.db, "get_setting", return_value="qwen:cloud") as get:
        response = await _request("GET", "/api/settings/active_model")
    assert response.status_code == 200
    assert response.json() == {"key": "active_model", "value": "qwen:cloud"}
    get.assert_called_once_with("active_model")

    with patch.object(settings.db, "set_setting") as set_value:
        response = await _request(
            "PUT",
            "/api/settings/active_model",
            json={"value": "kimi-k2.7-code:cloud"},
        )
    assert response.status_code == 200
    set_value.assert_called_once_with("active_model", "kimi-k2.7-code:cloud")

    invalid_keys = (
        "/api/settings/bad%20key",
        f"/api/settings/{'a' * 129}",
    )
    for url in invalid_keys:
        assert (await _request("GET", url)).status_code == 422
    assert (
        await _request("PUT", "/api/settings/active_model", json={})
    ).status_code == 422
    assert (
        await _request(
            "PUT",
            "/api/settings/active_model",
            json={"value": "x" * 1_048_577},
        )
    ).status_code == 422


def main() -> int:
    asyncio.run(_checks())
    print("Settings API OK - propriétaire unique, clés et valeurs bornées.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
