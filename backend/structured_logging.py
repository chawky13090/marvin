"""Journalisation JSONL bornée, portable et sûre pour les composants Marvin."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = "1.0"
_SECRET_MARKERS = (
    "password", "passwd", "token", "secret", "api_key", "apikey", "credential",
    "private_key", "authorization", "cookie", "session_id", "connection_string",
)
_CONTENT_MARKERS = (
    "prompt", "response", "answer", "content", "body", "message_text", "email_body",
    "document_text", "result_message", "query", "command", "script", "code", "transcript",
)
_INLINE_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(bearer|basic)\s+[a-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)\b(password|passwd|token|secret|api[_-]?key|authorization)"
        r"\s*[:=]\s*([^\s,;]+)"
    ),
)


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return min(max(value, minimum), maximum)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sanitize_text(value: Any, max_length: int = 2000) -> str:
    text = str(value)
    for pattern in _INLINE_SECRET_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}=***", text)
    return text[:max_length] + ("…" if len(text) > max_length else "")


def _content_fingerprint(value: Any) -> dict[str, Any]:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    except Exception:
        encoded = str(type(value).__name__).encode("utf-8")
    return {
        "redacted": True,
        "length": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def sanitize(value: Any, *, max_length: int = 2000, depth: int = 0) -> Any:
    """Supprime secrets et contenus utilisateur tout en gardant une preuve exploitable."""
    if depth > 8:
        return "<depth-limit>"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:100]:
            key = sanitize_text(raw_key, 120)
            lowered = key.lower()
            if any(marker in lowered for marker in _SECRET_MARKERS):
                result[key] = "***"
            elif any(marker in lowered for marker in _CONTENT_MARKERS):
                result[key] = _content_fingerprint(item)
            else:
                result[key] = sanitize(item, max_length=max_length, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [sanitize(item, max_length=max_length, depth=depth + 1) for item in list(value)[:100]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return sanitize_text(value, max_length)


class StructuredJsonlStore:
    """Fichier actif + archives horodatées, bornés par âge, nombre et taille totale."""

    def __init__(
        self,
        path: str | Path,
        *,
        component: str,
        retention_days: int = 30,
        max_bytes: int = 10 * 1024 * 1024,
        max_archives: int = 30,
        max_total_bytes: int = 300 * 1024 * 1024,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.path = Path(path).resolve()
        self.component = str(component)[:100]
        self.retention_days = min(max(int(retention_days), 1), 3650)
        self.max_bytes = min(max(int(max_bytes), 1024), 1024 * 1024 * 1024)
        self.max_archives = min(max(int(max_archives), 1), 1000)
        self.max_total_bytes = max(int(max_total_bytes), self.max_bytes)
        self._clock = clock
        self._lock = threading.RLock()
        self._rotation_counter = 0

    @classmethod
    def from_environment(
        cls,
        path: str | Path,
        *,
        component: str,
        prefix: str,
        default_retention_days: int,
    ) -> "StructuredJsonlStore":
        return cls(
            path,
            component=component,
            retention_days=_bounded_int(
                f"MARVIN_{prefix}_RETENTION_DAYS", default_retention_days, 1, 3650
            ),
            max_bytes=_bounded_int(
                f"MARVIN_{prefix}_MAX_BYTES", 10 * 1024 * 1024, 64 * 1024, 1024**3
            ),
            max_archives=_bounded_int(f"MARVIN_{prefix}_MAX_ARCHIVES", 30, 1, 1000),
            max_total_bytes=_bounded_int(
                f"MARVIN_{prefix}_MAX_TOTAL_BYTES",
                300 * 1024 * 1024,
                1024 * 1024,
                10 * 1024**3,
            ),
        )

    def _archives(self) -> list[Path]:
        pattern = f"{self.path.stem}.*{self.path.suffix}"
        return sorted(
            (item for item in self.path.parent.glob(pattern) if item != self.path),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )

    def _rotate_if_needed(self, projected_bytes: int) -> None:
        if not self.path.exists() or self.path.stat().st_size + projected_bytes <= self.max_bytes:
            return
        now = self._clock().astimezone(timezone.utc)
        stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        self._rotation_counter += 1
        archive = self.path.with_name(
            f"{self.path.stem}.{stamp}.{self._rotation_counter:04d}{self.path.suffix}"
        )
        os.replace(self.path, archive)

    def _prune(self) -> None:
        cutoff = self._clock().astimezone(timezone.utc) - timedelta(days=self.retention_days)
        for archive in self._archives():
            modified = datetime.fromtimestamp(archive.stat().st_mtime, timezone.utc)
            if modified < cutoff:
                archive.unlink(missing_ok=True)
        archives = self._archives()
        for archive in archives[self.max_archives :]:
            archive.unlink(missing_ok=True)
        archives = self._archives()
        total = (self.path.stat().st_size if self.path.exists() else 0) + sum(
            archive.stat().st_size for archive in archives
        )
        for archive in reversed(archives):
            if total <= self.max_total_bytes:
                break
            size = archive.stat().st_size
            archive.unlink(missing_ok=True)
            total -= size

    def write(
        self,
        event_name: str,
        *,
        severity: str = "INFO",
        outcome: str = "success",
        trace_id: str | None = None,
        attributes: dict[str, Any] | None = None,
        compatibility: dict[str, Any] | None = None,
    ) -> bool:
        """Écrit en best-effort; une panne de logs ne casse jamais l'action métier."""
        try:
            now = self._clock().astimezone(timezone.utc)
            record: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "timestamp": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "severity_text": str(severity).upper()[:20],
                "event_name": sanitize_text(event_name, 160),
                "component": self.component,
                "outcome": sanitize_text(outcome, 40),
            }
            if trace_id:
                record["trace_id"] = sanitize_text(trace_id, 128)
            if attributes:
                record["attributes"] = sanitize(attributes)
            if compatibility:
                record.update(sanitize(compatibility))
            record.setdefault("ts", record["timestamp"])
            encoded = (
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed(len(encoded))
                with self.path.open("ab") as stream:
                    stream.write(encoded)
                    stream.flush()
                self._prune()
            return True
        except Exception:
            return False

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        bounded_limit = min(max(int(limit), 1), 5000)
        with self._lock:
            paths = ([self.path] if self.path.exists() else []) + self._archives()
            result: list[dict[str, Any]] = []
            for path in paths:
                with path.open("r", encoding="utf-8", errors="replace") as stream:
                    tail = deque(stream, maxlen=bounded_limit)
                for line in reversed(tail):
                    try:
                        result.append(json.loads(line))
                    except (TypeError, ValueError):
                        continue
                    if len(result) >= bounded_limit:
                        return result
            return result

    def clear(self) -> bool:
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text("", encoding="utf-8")
                for archive in self._archives():
                    archive.unlink(missing_ok=True)
            return True
        except Exception:
            return False
