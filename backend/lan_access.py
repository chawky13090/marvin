"""Identité de session et garde ASGI pour l'accès LAN à Marvin."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import defaultdict, deque
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlsplit

import secret_vault


SESSION_COOKIE = "marvin_session"
CSRF_COOKIE = "marvin_csrf"
SESSION_SECONDS = 12 * 60 * 60
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/lan/status",
    "/api/auth/lan/pair",
    "/api/auth/lan/introspect",
}
MAX_PAIR_ATTEMPTS = 5
PAIR_WINDOW_SECONDS = 10 * 60


class LanAccessError(RuntimeError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str, *, maximum: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise LanAccessError("Jeton de session invalide.")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise LanAccessError("Jeton de session invalide.") from exc


def is_loopback(host: str | None) -> bool:
    return str(host or "").split("%", 1)[0] in {"127.0.0.1", "::1"}


def _headers(scope: dict[str, Any]) -> dict[str, str]:
    return {
        key.decode("latin-1").casefold(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _cookies(headers: dict[str, str]) -> dict[str, str]:
    parsed = SimpleCookie()
    try:
        parsed.load(headers.get("cookie", ""))
    except Exception:
        return {}
    return {name: morsel.value for name, morsel in parsed.items()}


def _origin_allowed(origin: str, host_header: str) -> bool:
    try:
        source = urlsplit(origin)
        target = urlsplit(f"//{host_header}")
        target_host = str(target.hostname or "").casefold()
    except (TypeError, ValueError):
        return False
    return (
        source.scheme in {"http", "https"}
        and str(source.hostname or "").casefold() == target_host
        and source.port in {3000, 8005}
    )


class LanAccessManager:
    def __init__(
        self,
        *,
        pairing_code: str | None = None,
        clock=time.time,
        secret_loader=None,
    ) -> None:
        self.pairing_code = pairing_code or secrets.token_urlsafe(12)
        self._clock = clock
        self._secret_loader = secret_loader or self._load_secret
        self._secret_cache: bytes | None = None
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()

    def _secret(self) -> bytes:
        with self._lock:
            if self._secret_cache is None:
                value = self._secret_loader()
                if not isinstance(value, bytes) or len(value) != 32:
                    raise LanAccessError("Secret de session LAN invalide.")
                self._secret_cache = value
            return self._secret_cache

    @staticmethod
    def _load_secret() -> bytes:
        encoded = secret_vault.get_secret("lanaccess", "installation", "hmac_key")
        if encoded is None:
            raw = secrets.token_bytes(32)
            encoded = _b64encode(raw)
            secret_vault.set_secret(
                "lanaccess",
                "installation",
                "hmac_key",
                encoded,
            )
            return raw
        secret = _b64decode(encoded, maximum=128)
        if len(secret) != 32:
            raise LanAccessError("Secret de session LAN invalide.")
        return secret

    def _prune_attempts(self, client: str) -> deque[float]:
        now = self._clock()
        attempts = self._attempts[client]
        while attempts and now - attempts[0] > PAIR_WINDOW_SECONDS:
            attempts.popleft()
        return attempts

    def pair(self, client: str, code: str) -> tuple[str, str]:
        with self._lock:
            attempts = self._prune_attempts(client)
            if len(attempts) >= MAX_PAIR_ATTEMPTS:
                raise LanAccessError("Trop de tentatives de jumelage.")
            if not hmac.compare_digest(str(code or ""), self.pairing_code):
                attempts.append(self._clock())
                raise LanAccessError("Code de jumelage invalide.")
            attempts.clear()
        return self.issue(client)

    def issue(self, client: str) -> tuple[str, str]:
        """Émet une session signée; réservé aux frontières déjà authentifiées."""
        now = int(self._clock())
        csrf = secrets.token_urlsafe(24)
        payload = {
            "v": 1,
            "iat": now,
            "exp": now + SESSION_SECONDS,
            "csrf": csrf,
            "sid": secrets.token_urlsafe(18),
            "client": hashlib.sha256(client.encode("utf-8")).hexdigest()[:32],
        }
        encoded = _b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signature = _b64encode(
            hmac.new(self._secret(), encoded.encode("ascii"), hashlib.sha256).digest()
        )
        return f"{encoded}.{signature}", csrf

    def verify(self, token: str, *, client: str | None = None) -> dict[str, Any]:
        try:
            encoded, signature = str(token or "").split(".", 1)
            expected = hmac.new(
                self._secret(),
                encoded.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(_b64decode(signature, maximum=128), expected):
                raise LanAccessError("Signature de session invalide.")
            payload = json.loads(_b64decode(encoded, maximum=2048))
        except (
            ValueError,
            TypeError,
            OverflowError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise LanAccessError("Jeton de session invalide.") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or not isinstance(payload.get("csrf"), str)
            or len(payload["csrf"]) < 24
            or int(payload.get("exp") or 0) <= int(self._clock())
            or int(payload.get("iat") or 0) > int(self._clock()) + 30
        ):
            raise LanAccessError("Session LAN expirée ou invalide.")
        if client is not None and not hmac.compare_digest(
            str(payload.get("client") or ""),
            hashlib.sha256(client.encode("utf-8")).hexdigest()[:32],
        ):
            raise LanAccessError("La session LAN appartient à un autre client.")
        return payload

    def authenticated(
        self,
        headers: dict[str, str],
        *,
        client: str | None = None,
    ) -> dict[str, Any] | None:
        token = _cookies(headers).get(SESSION_COOKIE)
        if not token:
            return None
        try:
            return self.verify(token, client=client)
        except LanAccessError:
            return None


ACCESS = LanAccessManager()


class LanAccessMiddleware:
    """Protège HTTP et WebSocket distants, et les mutations navigateur locales."""

    def __init__(self, app, *, manager: LanAccessManager = ACCESS) -> None:
        self.app = app
        self.manager = manager

    async def _reject(self, scope, receive, send, status: int, code: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return
        body = json.dumps({"detail": code}, separators=(",", ":")).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"cache-control", b"no-store"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET").upper()
        if scope["type"] == "http" and (method == "OPTIONS" or path in PUBLIC_PATHS):
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        client = (scope.get("client") or ("", 0))[0]
        session = self.manager.authenticated(headers, client=client)
        if not is_loopback(client) and session is None:
            await self._reject(scope, receive, send, 401, "lan_authentication_required")
            return
        if scope["type"] == "http" and method not in SAFE_METHODS:
            browser_request = "origin" in headers or "sec-fetch-site" in headers
            if browser_request:
                if not _origin_allowed(headers.get("origin", ""), headers.get("host", "")):
                    await self._reject(scope, receive, send, 403, "origin_rejected")
                    return
                cookies = _cookies(headers)
                csrf = headers.get("x-marvin-csrf", "")
                expected = (
                    session.get("csrf")
                    if session is not None
                    else cookies.get(CSRF_COOKIE)
                )
                if (
                    not csrf
                    or not expected
                    or not hmac.compare_digest(str(csrf), str(expected))
                ):
                    await self._reject(scope, receive, send, 403, "csrf_rejected")
                    return
        await self.app(scope, receive, send)
