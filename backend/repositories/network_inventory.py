"""Persistance injectable de l'inventaire réseau découvert."""

from __future__ import annotations

import ipaddress
import json
import re
import uuid
from contextlib import AbstractContextManager
from typing import Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]
_MAX_LOOKBACK_DAYS = 3_650
_MAX_TEXT = 500
_ASSET_TYPES = {
    "unknown", "switch", "router", "firewall", "access_point", "server",
    "workstation", "printer", "storage", "hypervisor", "appliance", "iot",
}
_OS_FAMILIES = {"", "windows", "linux", "network", "bsd", "unix", "embedded", "other"}
_PROTOCOLS = {
    "ssh", "snmpv3", "snmpv2c", "winrm", "https", "netconf", "restconf",
    "gnmi", "rdp", "wmi", "cim",
}
_SECRET_FIELDS = {
    "password", "passphrase", "private_key", "community", "auth_key", "priv_key",
    "token", "api_key", "secret",
}
_HOST_RE = re.compile(r"(?=^.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.I)
_SECRET_VALUE_RE = re.compile(
    r"(?:password|passphrase|community|token|api[_ -]?key|secret)\s*[:=]\s*\S+"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+[A-Za-z0-9._~+/=-]+",
    re.I,
)


class NetworkInventoryRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS network_devices (
                id TEXT PRIMARY KEY,
                ip TEXT NOT NULL,
                mac TEXT DEFAULT '',
                hostname TEXT DEFAULT '',
                custom_name TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(mac, ip)
            )"""
        )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_network_devices_last_seen
               ON network_devices(last_seen DESC)"""
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(network_devices)")
        }
        additions = {
            "asset_type": "TEXT NOT NULL DEFAULT 'unknown'",
            "vendor": "TEXT NOT NULL DEFAULT ''",
            "model": "TEXT NOT NULL DEFAULT ''",
            "os_family": "TEXT NOT NULL DEFAULT ''",
            "role": "TEXT NOT NULL DEFAULT ''",
            "site": "TEXT NOT NULL DEFAULT ''",
            "management_protocols": "TEXT NOT NULL DEFAULT '[]'",
            "tags": "TEXT NOT NULL DEFAULT '[]'",
            "ssh_connection_id": "TEXT NOT NULL DEFAULT ''",
            "snmp_profile_id": "TEXT NOT NULL DEFAULT ''",
            "enabled": "INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))",
            "source": "TEXT NOT NULL DEFAULT 'discovery'",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE network_devices ADD COLUMN {name} {declaration}"
                )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_network_devices_asset_type ON network_devices(asset_type, enabled)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_network_devices_site ON network_devices(site, enabled)"
        )

    @staticmethod
    def _normalize_address(value: str) -> str:
        address = str(value or "").strip()
        if not address:
            raise ValueError("L'adresse de gestion est obligatoire.")
        try:
            return ipaddress.ip_address(address).compressed
        except ValueError:
            normalized = address.rstrip(".").casefold()
            if not _HOST_RE.fullmatch(normalized):
                raise ValueError("Adresse IP ou nom DNS de gestion invalide.")
            return normalized

    @staticmethod
    def _text(value: object, field: str) -> str:
        normalized = str(value or "").strip()
        if len(normalized) > _MAX_TEXT:
            raise ValueError(f"Le champ {field} dépasse {_MAX_TEXT} caractères.")
        if field == "notes" and _SECRET_VALUE_RE.search(normalized):
            raise ValueError("Les notes du registre ne peuvent pas contenir un secret.")
        return normalized

    @staticmethod
    def _string_list(value: object, field: str, allowed: set[str] | None = None) -> list[str]:
        if value is None or value == "":
            return []
        raw = value.split(",") if isinstance(value, str) else value
        if not isinstance(raw, (list, tuple, set)):
            raise ValueError(f"Le champ {field} doit être une liste.")
        result = sorted({str(item).strip().casefold() for item in raw if str(item).strip()})
        if len(result) > 32 or any(len(item) > 64 for item in result):
            raise ValueError(f"Le champ {field} dépasse les limites autorisées.")
        if allowed is not None:
            unknown = sorted(set(result) - allowed)
            if unknown:
                raise ValueError(f"{field} non pris en charge : {', '.join(unknown)}")
        return result

    def upsert(self, ip: str, mac: str = "", hostname: str = "") -> dict:
        normalized_ip = self._normalize_address(ip)
        normalized_mac = str(mac or "").strip()
        normalized_hostname = str(hostname or "").strip()
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            existing = connection.execute(
                """SELECT id FROM network_devices
                   WHERE ip = ? AND mac = ?""",
                (normalized_ip, normalized_mac),
            ).fetchone()
            if existing:
                connection.execute(
                    """UPDATE network_devices
                       SET hostname = CASE WHEN ? <> '' THEN ? ELSE hostname END,
                           last_seen = datetime('now'), updated_at = datetime('now')
                       WHERE id = ?""",
                    (normalized_hostname, normalized_hostname, existing["id"]),
                )
                return {"id": existing["id"], "new": False}
            device_id = str(uuid.uuid4())
            connection.execute(
                """INSERT INTO network_devices (id, ip, mac, hostname)
                   VALUES (?, ?, ?, ?)""",
                (
                    device_id,
                    normalized_ip,
                    normalized_mac,
                    normalized_hostname,
                ),
            )
            return {"id": device_id, "new": True}

    def register(self, address: str, **metadata: object) -> dict:
        """Crée ou complète un actif sans accepter aucun secret d'administration."""
        forbidden = sorted(set(metadata) & _SECRET_FIELDS)
        if forbidden:
            raise ValueError("Les secrets ne peuvent pas être stockés dans le registre d'actifs.")
        normalized = self._normalize_address(address)
        result = self.upsert(normalized, str(metadata.get("mac") or ""), str(metadata.get("hostname") or ""))
        metadata["source"] = "manual"
        return self.set_metadata(str(result["id"]), **metadata)

    def list_recent(self, days: int = 30) -> list[dict]:
        bounded_days = min(max(int(days), 1), _MAX_LOOKBACK_DAYS)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                """SELECT * FROM network_devices
                   WHERE last_seen >= datetime('now', ?)
                   ORDER BY last_seen DESC, id ASC""",
                (f"-{bounded_days} days",),
            ).fetchall()
        results = []
        for row in rows:
            item = row_to_dict(row) or {}
            for field in ("management_protocols", "tags"):
                try:
                    item[field] = json.loads(item.get(field) or "[]")
                except (TypeError, json.JSONDecodeError):
                    item[field] = []
            item["enabled"] = bool(item.get("enabled"))
            results.append(item)
        return results

    def set_metadata(
        self,
        device_id: str,
        custom_name: str | None = None,
        notes: str | None = None,
        **metadata: object,
    ) -> dict:
        forbidden = sorted(set(metadata) & _SECRET_FIELDS)
        if forbidden:
            raise ValueError("Les secrets ne peuvent pas être stockés dans le registre d'actifs.")
        assignments: list[str] = []
        values: list[object] = []
        if custom_name is not None:
            assignments.append("custom_name = ?")
            values.append(self._text(custom_name, "custom_name"))
        if notes is not None:
            assignments.append("notes = ?")
            values.append(self._text(notes, "notes"))
        scalar_fields = {"vendor", "model", "role", "site", "ssh_connection_id", "snmp_profile_id", "source"}
        for field in scalar_fields:
            if field in metadata and metadata[field] is not None:
                if field == "ssh_connection_id" and metadata[field]:
                    try:
                        uuid.UUID(str(metadata[field]))
                    except (ValueError, AttributeError) as exc:
                        raise ValueError("Référence de connexion SSH invalide.") from exc
                if field == "snmp_profile_id" and metadata[field]:
                    try:
                        uuid.UUID(str(metadata[field]))
                    except (ValueError, AttributeError) as exc:
                        raise ValueError("Référence de profil SNMPv3 invalide.") from exc
                assignments.append(f"{field} = ?")
                values.append(self._text(metadata[field], field))
        if "asset_type" in metadata and metadata["asset_type"] is not None:
            asset_type = self._text(metadata["asset_type"], "asset_type").casefold()
            if asset_type not in _ASSET_TYPES:
                raise ValueError("Type d'actif non pris en charge.")
            assignments.append("asset_type = ?")
            values.append(asset_type)
        if "os_family" in metadata and metadata["os_family"] is not None:
            os_family = self._text(metadata["os_family"], "os_family").casefold()
            if os_family not in _OS_FAMILIES:
                raise ValueError("Famille de système non prise en charge.")
            assignments.append("os_family = ?")
            values.append(os_family)
        for field, allowed in (("management_protocols", _PROTOCOLS), ("tags", None)):
            if field in metadata and metadata[field] is not None:
                assignments.append(f"{field} = ?")
                values.append(json.dumps(self._string_list(metadata[field], field, allowed), ensure_ascii=False))
        if "enabled" in metadata and metadata["enabled"] is not None:
            if not isinstance(metadata["enabled"], bool):
                raise ValueError("Le champ enabled doit être booléen.")
            assignments.append("enabled = ?")
            values.append(1 if metadata["enabled"] else 0)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            if assignments:
                assignments.append("updated_at = datetime('now')")
                connection.execute(
                    f"UPDATE network_devices SET {', '.join(assignments)} "
                    "WHERE id = ?",
                    (*values, device_id),
                )
            row = connection.execute(
                "SELECT * FROM network_devices WHERE id = ?", (device_id,)
            ).fetchone()
        if row is None:
            raise ValueError("Actif d'infrastructure introuvable.")
        result = row_to_dict(row) or {}
        for field in ("management_protocols", "tags"):
            try:
                result[field] = json.loads(result.get(field) or "[]")
            except (TypeError, json.JSONDecodeError):
                result[field] = []
        result["enabled"] = bool(result.get("enabled"))
        return {"success": True, "device": result}

    def set_notes(
        self,
        device_id: str,
        custom_name: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """Compatibilité du contrat historique de simple annotation."""
        self.set_metadata(
            device_id, custom_name=custom_name, notes=notes
        )
        return {"success": True}


repository = NetworkInventoryRepository()
upsert_network_device = repository.upsert
register_network_device = repository.register
get_network_devices = repository.list_recent
set_network_device_notes = repository.set_metadata


def get_network_device(device_id: str) -> dict | None:
    for device in repository.list_recent(_MAX_LOOKBACK_DAYS):
        if str(device.get("id")) == str(device_id):
            return device
    return None
