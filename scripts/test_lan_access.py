"""Contrats d'identité LAN, session, CSRF et WebSocket."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from lan_access import (
    CSRF_COOKIE,
    MAX_PAIR_ATTEMPTS,
    SESSION_COOKIE,
    LanAccessError,
    LanAccessManager,
    LanAccessMiddleware,
)


async def _request(
    middleware,
    *,
    client: str,
    method: str = "GET",
    path: str = "/api/tasks",
    headers: dict[str, str] | None = None,
    scope_type: str = "http",
) -> list[dict]:
    messages: list[dict] = []

    async def receive():
        return {"type": f"{scope_type}.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": scope_type,
        "method": method,
        "path": path,
        "client": (client, 50000),
        "headers": [
            (key.encode("latin-1"), value.encode("latin-1"))
            for key, value in (headers or {}).items()
        ],
    }
    await middleware(scope, receive, send)
    return messages


def _status(messages: list[dict]) -> int:
    return next(message["status"] for message in messages if message["type"] == "http.response.start")


def main() -> int:
    now = [1_000_000.0]
    manager = LanAccessManager(
        pairing_code="verified-pair-code",
        clock=lambda: now[0],
        secret_loader=lambda: b"K" * 32,
    )

    async def app(scope, _receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.accept"})
        else:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

    middleware = LanAccessMiddleware(app, manager=manager)
    assert _status(asyncio.run(_request(middleware, client="127.0.0.1"))) == 200
    assert _status(asyncio.run(_request(middleware, client="192.168.1.50"))) == 401

    token, csrf = manager.pair("192.168.1.50", "verified-pair-code")
    cookie = f"{SESSION_COOKIE}={token}; {CSRF_COOKIE}={csrf}"
    assert _status(asyncio.run(_request(
        middleware,
        client="192.168.1.50",
        headers={"cookie": cookie},
    ))) == 200
    assert _status(asyncio.run(_request(
        middleware,
        client="192.168.1.51",
        headers={"cookie": cookie},
    ))) == 401
    browser = {
        "cookie": cookie,
        "origin": "http://192.168.1.10:3000",
        "host": "192.168.1.10:8005",
        "sec-fetch-site": "same-site",
        "x-marvin-csrf": csrf,
    }
    assert _status(asyncio.run(_request(
        middleware,
        client="192.168.1.50",
        method="POST",
        headers=browser,
    ))) == 200
    read_token, read_csrf = manager.issue("192.168.1.70", profile="read_only")
    read_cookie = f"{SESSION_COOKIE}={read_token}; {CSRF_COOKIE}={read_csrf}"
    assert _status(asyncio.run(_request(
        middleware,
        client="192.168.1.70",
        headers={"cookie": read_cookie},
    ))) == 200
    assert _status(asyncio.run(_request(
        middleware,
        client="192.168.1.70",
        path="/api/settings/privacy",
        headers={"cookie": read_cookie},
    ))) == 403
    assert _status(asyncio.run(_request(
        middleware,
        client="192.168.1.70",
        method="POST",
        headers={
            "cookie": read_cookie,
            "origin": "http://192.168.1.10:3000",
            "host": "192.168.1.10:8005",
            "x-marvin-csrf": read_csrf,
        },
    ))) == 403
    without_csrf = {key: value for key, value in browser.items() if key != "x-marvin-csrf"}
    assert _status(asyncio.run(_request(
        middleware,
        client="192.168.1.50",
        method="POST",
        headers=without_csrf,
    ))) == 403
    wrong_origin = {**browser, "origin": "https://attacker.example"}
    assert _status(asyncio.run(_request(
        middleware,
        client="192.168.1.50",
        method="DELETE",
        headers=wrong_origin,
    ))) == 403

    local_csrf = "local-csrf-token-with-enough-entropy"
    assert _status(asyncio.run(_request(
        middleware,
        client="::1",
        method="PATCH",
        headers={
            "cookie": f"{CSRF_COOKIE}={local_csrf}",
            "origin": "http://localhost:3000",
            "host": "localhost:8005",
            "x-marvin-csrf": local_csrf,
        },
    ))) == 200
    websocket = asyncio.run(_request(
        middleware,
        client="192.168.1.51",
        scope_type="websocket",
    ))
    assert websocket == [{"type": "websocket.close", "code": 4401}]

    now[0] += 12 * 60 * 60 + 1
    try:
        manager.verify(token)
    except LanAccessError:
        pass
    else:
        raise AssertionError("Une session expirée doit être refusée.")

    limiter = LanAccessManager(
        pairing_code="another-valid-code",
        clock=lambda: now[0],
        secret_loader=lambda: b"L" * 32,
    )
    for _ in range(MAX_PAIR_ATTEMPTS):
        try:
            limiter.pair("192.168.1.60", "invalid-code-value")
        except LanAccessError:
            pass
    try:
        limiter.pair("192.168.1.60", "another-valid-code")
    except LanAccessError:
        pass
    else:
        raise AssertionError("Le rate limit de jumelage doit être fermé.")

    print("LAN Access OK - session signée, CSRF, origine, expiration, rate limit et WebSocket.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
