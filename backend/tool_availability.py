"""Runtime availability for the versioned Marvin tool dependency inventory.

The inventory describes execution prerequisites only. It does not authorize,
select or execute a tool and therefore cannot bypass the policy engine.
"""

from __future__ import annotations

import asyncio
import ctypes
import http.client
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit


MANIFEST_PATH = Path(__file__).with_name("resources") / "tool_network_dependencies.json"
SCHEMA = "marvin.tool-network-dependencies/1.0"
_VALID_NETWORK = frozenset({"local", "internet", "target"})
_VALID_SERVICES = frozenset({"ollama", "searxng"})
_CACHE_SECONDS = 20.0


class ToolDependencyInventoryError(RuntimeError):
    """The dependency inventory is missing, malformed or incomplete."""


@dataclass(frozen=True, slots=True)
class ConnectivitySnapshot:
    internet: bool | None
    services: Mapping[str, bool | None]
    observed_at: float


_cached_snapshot: ConnectivitySnapshot | None = None
_cache_deadline = 0.0
_snapshot_lock = asyncio.Lock()


def load_inventory(path: Path = MANIFEST_PATH) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolDependencyInventoryError(
            f"Inventaire des dependances outils illisible ({type(exc).__name__})."
        ) from exc
    tools = payload.get("tools")
    if payload.get("schema") != SCHEMA or not isinstance(tools, dict):
        raise ToolDependencyInventoryError("Schema de dependances outils invalide.")
    result: dict[str, dict[str, Any]] = {}
    for raw_name, raw_entry in tools.items():
        name = str(raw_name or "").strip()
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        network = str(entry.get("network") or "")
        services = entry.get("services")
        offline_capable = entry.get("offline_capable", False)
        if (
            not name
            or network not in _VALID_NETWORK
            or not isinstance(services, list)
            or any(str(service) not in _VALID_SERVICES for service in services)
            or not isinstance(offline_capable, bool)
        ):
            raise ToolDependencyInventoryError(
                f"Dependance invalide pour l'outil {name or '<vide>'}."
            )
        result[name] = {
            "network": network,
            "services": list(dict.fromkeys(str(service) for service in services)),
            "offline_capable": offline_capable,
        }
    return result


def validate_coverage(tool_names: Iterable[str]) -> dict[str, Any]:
    inventory = load_inventory()
    expected = {str(name) for name in tool_names if str(name)}
    actual = set(inventory)
    missing = sorted(expected - actual)
    orphaned = sorted(actual - expected)
    return {
        "schema": SCHEMA,
        "tool_count": len(expected),
        "inventory_count": len(actual),
        "missing": missing,
        "orphaned": orphaned,
        "valid": not missing and not orphaned,
    }


def _windows_internet_state() -> bool | None:
    """Read the Windows connectivity flag without network traffic or a shell."""
    if os.name != "nt":
        return None
    try:
        flags = ctypes.c_ulong(0)
        connected = ctypes.windll.wininet.InternetGetConnectedState(  # type: ignore[attr-defined]
            ctypes.byref(flags), 0
        )
        return bool(connected)
    except (AttributeError, OSError):
        return None


async def _probe_services() -> dict[str, bool | None]:
    from config import OLLAMA_URL
    import credentials_manager as credentials

    try:
        searxng_url = str(credentials.get_credential("searxng_url") or "").rstrip("/")
    except (OSError, RuntimeError, ValueError):
        # A vault failure must not take down chat/tool selection. The service is
        # conservatively reported unavailable until the vault is repaired.
        searxng_url = ""
    endpoints = {
        "ollama": f"{OLLAMA_URL.rstrip('/')}/api/tags",
        "searxng": f"{searxng_url}/config" if searxng_url else "",
    }

    def probe_sync(url: str) -> bool | None:
        if not url:
            return False
        connection: http.client.HTTPConnection | None = None
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return False
            connection_type = (
                http.client.HTTPSConnection
                if parsed.scheme == "https"
                else http.client.HTTPConnection
            )
            # The bundled services listen on IPv4. On some Windows hosts,
            # ``localhost`` resolves to ::1 first and waits for the full timeout.
            host = "127.0.0.1" if parsed.hostname.casefold() == "localhost" else parsed.hostname
            connection = connection_type(
                host,
                parsed.port,
                timeout=1.5,
            )
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status < 500
        except (OSError, ValueError, http.client.HTTPException):
            return False
        finally:
            if connection is not None:
                connection.close()

    # These are local/private service endpoints. Ignoring host proxy variables
    # avoids a costly Windows proxy discovery on every cache refresh and prevents
    # local health traffic from leaving the machine.
    values = await asyncio.gather(
        *(asyncio.to_thread(probe_sync, url) for url in endpoints.values())
    )
    return dict(zip(endpoints, values, strict=True))


async def get_snapshot(*, force: bool = False) -> ConnectivitySnapshot:
    global _cached_snapshot, _cache_deadline
    now = time.monotonic()
    if not force and _cached_snapshot is not None and now < _cache_deadline:
        return _cached_snapshot
    async with _snapshot_lock:
        now = time.monotonic()
        if not force and _cached_snapshot is not None and now < _cache_deadline:
            return _cached_snapshot
        services = await _probe_services()
        _cached_snapshot = ConnectivitySnapshot(
            internet=_windows_internet_state(),
            services=services,
            observed_at=time.time(),
        )
        _cache_deadline = now + _CACHE_SECONDS
        return _cached_snapshot


def describe_availability(
    tool_name: str,
    snapshot: ConnectivitySnapshot,
    *,
    inventory: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    dependencies = inventory or load_inventory()
    entry = dependencies.get(str(tool_name or ""))
    if entry is None:
        raise ToolDependencyInventoryError(f"Outil absent de l'inventaire : {tool_name}")
    network = str(entry["network"])
    required_services = tuple(str(item) for item in entry.get("services") or [])
    offline_capable = bool(entry.get("offline_capable", False))
    reasons: list[str] = []
    unknown = False
    degraded = False
    if network == "internet":
        if snapshot.internet is False:
            if offline_capable:
                degraded = True
                reasons.append("internet_unavailable_offline_path_only")
            else:
                reasons.append("internet_unavailable")
        elif snapshot.internet is None:
            unknown = True
    elif network == "target":
        unknown = True
    for service in required_services:
        state = snapshot.services.get(service)
        if state is False:
            reasons.append(f"service_{service}_unavailable")
        elif state is None:
            unknown = True
    hard_failure = any(not reason.endswith("_offline_path_only") for reason in reasons)
    status = (
        "unavailable"
        if hard_failure
        else "degraded"
        if degraded
        else "unknown"
        if unknown
        else "available"
    )
    return {
        "status": status,
        # A degraded tool remains discoverable and usable when explicitly asked,
        # but does not consume a scarce ranked slot in local/offline profiles.
        "rankable": status not in {"unavailable", "degraded"},
        "network": network,
        "offline_capable": offline_capable,
        "required_services": list(required_services),
        "reasons": reasons,
        "observed_at": snapshot.observed_at,
    }


def availability_map(
    tool_names: Iterable[str],
    snapshot: ConnectivitySnapshot,
) -> dict[str, dict[str, Any]]:
    inventory = load_inventory()
    return {
        str(name): describe_availability(str(name), snapshot, inventory=inventory)
        for name in tool_names
    }
