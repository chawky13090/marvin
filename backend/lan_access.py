"""Identité de session et garde ASGI pour l'accès LAN à Marvin."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import ipaddress
import secrets
import socket
import threading
import time
from collections import defaultdict, deque
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlsplit

import api_observability
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
PAIR_CODE_SECONDS = 5 * 60
ACCESS_PROFILES = {
    "read_only": frozenset({"read"}),
    "standard": frozenset({"read", "operate"}),
    "full": frozenset({"read", "operate", "administer"}),
}
ADMIN_PATH_PREFIXES = (
    "/api/backups",
    "/api/cmd",
    "/api/coding",
    "/api/credentials",
    "/api/files",
    "/api/oauth",
    "/api/settings",
    "/api/ssh",
    "/api/storage",
    "/api/tools",
    "/api/vm-lab",
)


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


def local_interface_addresses() -> frozenset[str]:
    """Résout les adresses courantes du PC, y compris après un renouvellement DHCP."""
    addresses = {"127.0.0.1", "::1"}
    try:
        records = socket.getaddrinfo(
            socket.gethostname(),
            None,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        records = []
    for record in records:
        try:
            addresses.add(
                str(ipaddress.ip_address(str(record[4][0]).split("%", 1)[0]))
            )
        except (ValueError, TypeError, IndexError):
            continue
    return frozenset(addresses)


def is_local_client(
    host: str | None,
    *,
    local_addresses: frozenset[str] | set[str] | None = None,
) -> bool:
    """Reconnaît loopback et les interfaces du PC principal sans faire confiance au Host."""
    candidate = str(host or "").split("%", 1)[0]
    try:
        normalized = str(ipaddress.ip_address(candidate))
    except ValueError:
        return False
    return normalized in (
        frozenset(local_addresses)
        if local_addresses is not None
        else local_interface_addresses()
    )


def effective_client(host: str | None, headers: dict[str, str]) -> str:
    """Résout le client transmis uniquement par la passerelle locale de confiance."""
    direct = str(host or "")
    if not is_loopback(direct):
        return direct
    # La passerelle locale ajoute l'adresse réellement observée en fin de chaîne.
    # Prendre le premier élément ferait confiance à une valeur injectée par le client.
    forwarded = str(headers.get("x-forwarded-for") or "").rsplit(",", 1)[-1].strip()
    if not forwarded:
        return direct
    try:
        return str(ipaddress.ip_address(forwarded))
    except ValueError:
        return direct


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
    source_port = source.port or (443 if source.scheme == "https" else 80)
    target_port = target.port or (443 if source.scheme == "https" else 80)
    return (
        source.scheme in {"http", "https"}
        and str(source.hostname or "").casefold() == target_host
        and (source_port, target_port)
        in {(3000, 8005), (8005, 8005), (443, 443), (8443, 8443)}
    )


def required_capability(path: str, method: str, *, websocket: bool = False) -> str:
    normalized = str(path or "")
    if any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in ADMIN_PATH_PREFIXES
    ):
        return "administer"
    if websocket or str(method or "GET").upper() not in SAFE_METHODS:
        return "operate"
    return "read"


class LanAccessManager:
    def __init__(
        self,
        *,
        pairing_code: str | None = None,
        clock=time.time,
        secret_loader=None,
    ) -> None:
        self._clock = clock
        self._pairing_code = pairing_code or secrets.token_urlsafe(12)
        self._pairing_code_created_at = self._clock()
        self._secret_loader = secret_loader or self._load_secret
        self._secret_cache: bytes | None = None
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()

    @property
    def pairing_code(self) -> str:
        with self._lock:
            if self._clock() - self._pairing_code_created_at > PAIR_CODE_SECONDS:
                return ""
            return self._pairing_code

    def regenerate_pairing_code(self) -> str:
        with self._lock:
            self._pairing_code = secrets.token_urlsafe(12)
            self._pairing_code_created_at = self._clock()
            return self._pairing_code

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

    def pair(
        self,
        client: str,
        code: str,
        *,
        profile: str = "full",
    ) -> tuple[str, str]:
        with self._lock:
            attempts = self._prune_attempts(client)
            if len(attempts) >= MAX_PAIR_ATTEMPTS:
                raise LanAccessError("Trop de tentatives de jumelage.")
            active_code = self.pairing_code
            if not active_code or not hmac.compare_digest(str(code or ""), active_code):
                attempts.append(self._clock())
                raise LanAccessError("Code de jumelage invalide.")
            attempts.clear()
            self.regenerate_pairing_code()
        return self.issue(client, profile=profile)

    def issue(self, client: str, *, profile: str = "full") -> tuple[str, str]:
        """Émet une session signée; réservé aux frontières déjà authentifiées."""
        if profile not in ACCESS_PROFILES:
            raise LanAccessError("Profil d'accès LAN invalide.")
        now = int(self._clock())
        csrf = secrets.token_urlsafe(24)
        payload = {
            "v": 1,
            "iat": now,
            "exp": now + SESSION_SECONDS,
            "csrf": csrf,
            "sid": secrets.token_urlsafe(18),
            "client": hashlib.sha256(client.encode("utf-8")).hexdigest()[:32],
            "profile": profile,
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
            or payload.get("profile") not in ACCESS_PROFILES
        ):
            raise LanAccessError("Session LAN expirée ou invalide.")
        if client is not None and not hmac.compare_digest(
            str(payload.get("client") or ""),
            hashlib.sha256(client.encode("utf-8")).hexdigest()[:32],
        ):
            raise LanAccessError("La session LAN appartient à un autre client.")
        return payload

    @staticmethod
    def authorized(session: dict[str, Any], capability: str) -> bool:
        return capability in ACCESS_PROFILES.get(str(session.get("profile") or ""), ())

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
        decision = {
            "lan_authentication_required": "authentication_required",
            "capability_required": "capability_required",
            "origin_rejected": "origin_rejected",
            "csrf_rejected": "csrf_rejected",
        }.get(code)
        if decision is not None:
            api_observability.record_access_decision(decision)
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
        client = effective_client(
            (scope.get("client") or ("", 0))[0],
            headers,
        )
        session = self.manager.authenticated(headers, client=client)
        if not is_local_client(client) and session is None:
            await self._reject(scope, receive, send, 401, "lan_authentication_required")
            return
        if session is not None:
            capability = required_capability(
                path,
                method,
                websocket=scope["type"] == "websocket",
            )
            if not self.manager.authorized(session, capability):
                await self._reject(scope, receive, send, 403, "capability_required")
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
