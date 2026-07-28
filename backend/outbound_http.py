"""Transport HTTP sortant public, borné et résistant aux redirections SSRF."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

import httpx


Resolver = Callable[[str, int], Awaitable[list[str]]]
_MAX_REDIRECTS = 3
_ALLOWED_PORTS = {80, 443}


@dataclass(frozen=True)
class PublicResponse:
    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    elapsed_ms: int


async def _resolve(hostname: str, port: int) -> list[str]:
    records = await asyncio.to_thread(
        socket.getaddrinfo,
        hostname,
        port,
        type=socket.SOCK_STREAM,
    )
    return list(dict.fromkeys(record[4][0] for record in records))


def _parse_public_url(raw_url: str) -> tuple[SplitResult, int]:
    parsed = urlsplit(raw_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("L'URL doit utiliser HTTP ou HTTPS et contenir un hôte.")
    if parsed.username or parsed.password:
        raise ValueError("Les identifiants intégrés dans une URL sont interdits.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("Port URL invalide.") from exc
    if port not in _ALLOWED_PORTS:
        raise ValueError("Seuls les ports HTTP 80 et HTTPS 443 sont autorisés.")
    if len(parsed.hostname) > 253:
        raise ValueError("Nom d'hôte trop long.")
    return parsed, port


def _public_addresses(addresses: list[str]) -> list[str]:
    if not addresses:
        raise ValueError("L'hôte ne possède aucune adresse réseau.")
    validated: list[str] = []
    for raw_address in addresses:
        address = ipaddress.ip_address(raw_address.split("%", 1)[0])
        if not address.is_global:
            raise ValueError(
                f"Destination réseau non publique interdite : {address.compressed}"
            )
        validated.append(address.compressed)
    return validated


def _pinned_url(parsed: SplitResult, address: str, port: int) -> str:
    host = f"[{address}]" if ":" in address else address
    default_port = 443 if parsed.scheme == "https" else 80
    netloc = host if port == default_port else f"{host}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))


def _host_header(parsed: SplitResult, port: int) -> str:
    assert parsed.hostname is not None
    hostname = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    default_port = 443 if parsed.scheme == "https" else 80
    return hostname if port == default_port else f"{hostname}:{port}"


async def fetch_public(
    url: str,
    *,
    max_bytes: int = 1_000_000,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
    resolver: Resolver = _resolve,
) -> PublicResponse:
    """Télécharge une ressource publique en épinglant chaque connexion à une IP validée."""
    if not 1 <= max_bytes <= 10_000_000:
        raise ValueError("max_bytes doit être compris entre 1 et 10 000 000.")
    if not 0.5 <= timeout <= 60:
        raise ValueError("timeout doit être compris entre 0,5 et 60 secondes.")
    current_url = url.strip()
    started = time.perf_counter()
    timeout_config = httpx.Timeout(timeout, connect=min(timeout, 5.0))
    limits = httpx.Limits(max_connections=4, max_keepalive_connections=0)
    async with httpx.AsyncClient(
        timeout=timeout_config,
        follow_redirects=False,
        trust_env=False,
        limits=limits,
    ) as client:
        for redirect_count in range(_MAX_REDIRECTS + 1):
            parsed, port = _parse_public_url(current_url)
            assert parsed.hostname is not None
            addresses = _public_addresses(await resolver(parsed.hostname, port))
            last_error: Exception | None = None
            response: httpx.Response | None = None
            for address in addresses:
                request_headers = dict(headers or {})
                request_headers["Host"] = _host_header(parsed, port)
                request = client.build_request(
                    "GET",
                    _pinned_url(parsed, address, port),
                    headers=request_headers,
                )
                request.extensions["sni_hostname"] = parsed.hostname
                try:
                    response = await client.send(
                        request,
                        stream=True,
                        follow_redirects=False,
                    )
                    break
                except httpx.HTTPError as exc:
                    last_error = exc
            if response is None:
                assert last_error is not None
                raise last_error
            try:
                if response.is_redirect:
                    if redirect_count >= _MAX_REDIRECTS:
                        raise ValueError("La page dépasse la limite de 3 redirections.")
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirection HTTP sans destination.")
                    current_url = urljoin(current_url, location)
                    continue
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise ValueError(
                            f"La réponse HTTP dépasse la limite de {max_bytes} octets."
                        )
                return PublicResponse(
                    url=current_url,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    content=bytes(content),
                    elapsed_ms=round((time.perf_counter() - started) * 1000),
                )
            finally:
                await response.aclose()
    raise ValueError("La ressource HTTP n'a pas pu être téléchargée.")
