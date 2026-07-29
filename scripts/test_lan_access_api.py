"""Intégration FastAPI de la garde LAN et de ses cookies."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from lan_access import ACCESS, CSRF_COOKIE
from main import app
import api.lan_access as access_api


async def _run() -> None:
    previous_loader = ACCESS._secret_loader
    previous_cache = ACCESS._secret_cache
    previous_audit = access_api._audit_pair
    ACCESS._secret_loader = lambda: b"T" * 32
    ACCESS._secret_cache = None
    access_api._audit_pair = lambda _success, **_kwargs: None
    try:
        transport = httpx.ASGITransport(
            app=app,
            client=("192.168.1.50", 50000),
        )
        client = httpx.AsyncClient(
            transport=transport,
            base_url="http://marvin.local:8005",
        )
        status = await client.get("/api/auth/lan/status")
        assert status.status_code == 200
        assert status.json() == {
            "required": True,
            "authenticated": False,
            "transport_secure": False,
        }
        assert (await client.get("/api/health")).status_code == 200
        assert (await client.get("/api/tasks")).status_code == 401
        rejected = await client.post(
            "/api/auth/lan/pair",
            json={"code": "wrong-code-value"},
            headers={"Origin": "http://marvin.local:3000"},
        )
        assert rejected.status_code == 401
        paired = await client.post(
            "/api/auth/lan/pair",
            json={"code": ACCESS.pairing_code},
            headers={"Origin": "http://marvin.local:3000"},
        )
        assert paired.status_code == 200
        cookies = paired.headers.get_list("set-cookie")
        assert any("marvin_session=" in item and "HttpOnly" in item for item in cookies)
        assert any(
            "marvin_session=" in item and "SameSite=lax" in item
            for item in cookies
        )
        assert any(
            "marvin_csrf=" in item and "SameSite=strict" in item
            for item in cookies
        )
        assert (await client.get("/api/tasks")).status_code == 200
        introspection = await client.post("/api/auth/lan/introspect")
        assert introspection.status_code == 200
        assert introspection.json() == {"authenticated": True}
        blocked = await client.post(
            "/api/contract-only-test",
            headers={"Origin": "http://marvin.local:3000"},
        )
        assert blocked.status_code == 403
        csrf = client.cookies.get(CSRF_COOKIE)
        allowed_to_router = await client.post(
            "/api/contract-only-test",
            headers={
                "Origin": "http://marvin.local:3000",
                "X-Marvin-CSRF": csrf,
            },
        )
        assert allowed_to_router.status_code == 404
        schema = (await client.get("/openapi.json")).json()
        assert schema["paths"]["/api/tasks"]["get"]["security"] == [
            {"MarvinLanSession": []}
        ]
        assert "401" in schema["paths"]["/api/tasks"]["get"]["responses"]
        assert "403" in schema["paths"]["/api/tasks"]["post"]["responses"]
        with patch("audit.log_action"):
            logout = await client.post(
                "/api/auth/lan/logout",
                headers={
                    "Origin": "http://marvin.local:3000",
                    "X-Marvin-CSRF": csrf,
                },
            )
        assert logout.status_code == 200
        introspection = await client.post("/api/auth/lan/introspect")
        assert introspection.json() == {"authenticated": False}
        assert (await client.get("/api/tasks")).status_code == 401
        await client.aclose()
        print("LAN Access API OK - pairing, cookies, garde HTTP, CSRF et OpenAPI.")
    finally:
        ACCESS._secret_loader = previous_loader
        ACCESS._secret_cache = previous_cache
        access_api._audit_pair = previous_audit


def main() -> int:
    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
