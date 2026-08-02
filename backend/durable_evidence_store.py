"""Registre JSONL append-only pour preuves métier durables et vérifiables."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator


EVIDENCE_SCHEMA_VERSION = "1.0"
_MAX_RECORD_BYTES = 2 * 1024 * 1024
_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}
_INTEGRITY_FIELDS = frozenset({
    "evidence_schema_version", "sequence", "previous_hash", "record_hash"
})


class DuplicateEvidenceError(ValueError):
    """Une identité métier existe déjà dans le registre."""


def _path_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve()))
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def _canonical_bytes(record: dict[str, Any]) -> bytes:
    value = {key: item for key, item in record.items() if key != "record_hash"}
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(record: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(record)).hexdigest()


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"Constante JSON non finie interdite : {value}")


def _integrity_report(
    stream_name: str,
    rows: list[dict[str, Any]],
    corrupt: int,
) -> dict[str, Any]:
    previous_hash = None
    legacy = 0
    signed = 0
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        actual_hash = _digest(row)
        declared_hash = row.get("record_hash")
        if not declared_hash:
            legacy += 1
        else:
            signed += 1
            if declared_hash != actual_hash:
                errors.append({"sequence": index, "reason": "record_hash"})
            if row.get("previous_hash") != previous_hash:
                errors.append({"sequence": index, "reason": "previous_hash"})
            if row.get("sequence") != index:
                errors.append({"sequence": index, "reason": "sequence"})
        previous_hash = actual_hash
    valid = corrupt == 0 and not errors
    integrity_level = (
        "invalid"
        if not valid
        else "mixed_legacy_unsigned"
        if legacy
        else "tamper_evident"
    )
    return {
        "stream": stream_name,
        "valid": valid,
        "integrity_level": integrity_level,
        "records": len(rows),
        "signed_records": signed,
        "legacy_records": legacy,
        "corrupt_lines": corrupt,
        "errors": errors[:50],
        "last_hash": previous_hash,
        "retention": "owner_lifecycle",
    }


@contextmanager
def _interprocess_lock(path: Path, timeout_seconds: float = 5.0) -> Iterator[None]:
    """Verrou fichier borné, compatible Windows et Linux."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Verrou de preuves indisponible : {path.name}")
                time.sleep(0.02)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class DurableEvidenceStore:
    """Préserve les preuves sans rétention automatique et détecte les altérations."""

    def __init__(
        self,
        path: str | Path,
        *,
        stream_name: str,
        record_validator: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.path = Path(path).resolve()
        self.stream_name = str(stream_name).strip()[:120]
        if not self.stream_name:
            raise ValueError("Le nom du registre de preuves est requis.")
        self._record_validator = record_validator
        self._thread_lock = _path_lock(self.path)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def _integrity_unlocked(
        self,
        rows: list[dict[str, Any]],
        corrupt: int,
    ) -> dict[str, Any]:
        report = _integrity_report(self.stream_name, rows, corrupt)
        if self._record_validator is None:
            return report
        schema_errors = []
        for index, row in enumerate(rows, start=1):
            try:
                self._record_validator(row)
            except Exception:
                schema_errors.append({"sequence": index, "reason": "record_schema"})
        if schema_errors:
            report["valid"] = False
            report["integrity_level"] = "invalid"
            report["errors"] = (report["errors"] + schema_errors)[:50]
        return report

    def _repair_partial_tail_unlocked(self) -> Path | None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None
        raw = self.path.read_bytes()
        if raw.endswith(b"\n"):
            return None
        last_newline = raw.rfind(b"\n")
        valid = raw[: last_newline + 1] if last_newline >= 0 else b""
        partial = raw[last_newline + 1 :]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        quarantine = self.path.with_name(f"{self.path.name}.partial.{stamp}")
        quarantine.write_bytes(partial)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(valid)
        os.replace(temporary, self.path)
        return quarantine

    def _rows_unlocked(self) -> tuple[list[dict[str, Any]], int]:
        if not self.path.exists():
            return [], 0
        rows: list[dict[str, Any]] = []
        corrupt = 0
        with self.path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line, parse_constant=_reject_non_finite)
                except (TypeError, ValueError):
                    corrupt += 1
                    continue
                if isinstance(value, dict):
                    rows.append(value)
                else:
                    corrupt += 1
        return rows, corrupt

    @staticmethod
    def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise TypeError("Une preuve doit être un objet.")
        try:
            return json.loads(
                json.dumps(record, ensure_ascii=False, allow_nan=False, default=str)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Preuve non sérialisable : {exc}") from exc

    def _append_unlocked(
        self,
        normalized: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        previous_hash = _digest(rows[-1]) if rows else None
        enriched = {
            **normalized,
            "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
            "sequence": len(rows) + 1,
            "previous_hash": previous_hash,
        }
        enriched["record_hash"] = _digest(enriched)
        encoded = (
            json.dumps(
                enriched,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        if len(encoded) > _MAX_RECORD_BYTES:
            raise ValueError("Une preuve est limitée à 2 Mio.")
        with self.path.open("ab") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return enriched

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_record(record)
        with self._thread_lock, _interprocess_lock(self._lock_path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._repair_partial_tail_unlocked()
            rows, corrupt = self._rows_unlocked()
            if not self._integrity_unlocked(rows, corrupt)["valid"]:
                raise RuntimeError(
                    "L'intégrité du registre est compromise; ajout refusé avant réparation."
                )
            return self._append_unlocked(normalized, rows)

    def append_unique(
        self,
        record: dict[str, Any],
        *,
        unique_fields: tuple[str, ...],
    ) -> dict[str, Any]:
        """Ajoute atomiquement une preuve si son identité métier n'existe pas."""
        normalized = self._normalize_record(record)
        fields = tuple(str(item).strip() for item in unique_fields if str(item).strip())
        if not fields or any(field not in normalized for field in fields):
            raise ValueError("Les champs d'unicité doivent être présents dans la preuve.")
        with self._thread_lock, _interprocess_lock(self._lock_path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._repair_partial_tail_unlocked()
            rows, corrupt = self._rows_unlocked()
            if not self._integrity_unlocked(rows, corrupt)["valid"]:
                raise RuntimeError(
                    "L'intégrité du registre est compromise; ajout refusé avant réparation."
                )
            if any(
                all(row.get(field) == normalized.get(field) for field in fields)
                for row in rows
            ):
                raise DuplicateEvidenceError("Une preuve avec cette identité existe déjà.")
            return self._append_unlocked(normalized, rows)

    def recent(
        self,
        limit: int = 200,
        *,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
    ) -> list[dict[str, Any]]:
        bounded = min(max(int(limit), 0), 100_000)
        if bounded == 0 or not self.path.exists():
            return []
        with self._thread_lock, _interprocess_lock(self._lock_path):
            rows: deque[dict[str, Any]] = deque(maxlen=bounded)
            with self.path.open("r", encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    try:
                        value = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(value, dict) and (predicate is None or predicate(value)):
                        rows.append(value)
            return list(reversed(rows))

    def recent_verified(
        self,
        limit: int = 200,
        *,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
    ) -> list[dict[str, Any]]:
        """Vérifie puis projette les lignes sous le même verrou, sans fenêtre TOCTOU."""
        bounded = min(max(int(limit), 0), 100_000)
        if bounded == 0:
            return []
        with self._thread_lock, _interprocess_lock(self._lock_path):
            rows, corrupt = self._rows_unlocked()
            report = self._integrity_unlocked(rows, corrupt)
            if not report["valid"]:
                raise RuntimeError(
                    "L'intégrité du registre est compromise; lecture fiable impossible."
                )
            selected: deque[dict[str, Any]] = deque(maxlen=bounded)
            for row in rows:
                if predicate is None or predicate(row):
                    selected.append(row)
            return list(reversed(selected))

    def page(self, *, after: int = 0, limit: int = 500) -> dict[str, Any]:
        """Lit une page chronologique avec des curseurs de ligne stables."""
        start = max(0, int(after))
        bounded = min(max(int(limit), 1), 10_000)
        if not self.path.exists():
            return {"records": [], "cursor": 0}
        with self._thread_lock, _interprocess_lock(self._lock_path):
            rows: list[dict[str, Any]] = []
            cursor = 0
            with self.path.open("r", encoding="utf-8", errors="replace") as stream:
                for line_number, line in enumerate(stream, start=1):
                    cursor = line_number
                    if line_number <= start:
                        continue
                    try:
                        value = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(value, dict):
                        rows.append({**value, "cursor": line_number})
                        if len(rows) >= bounded:
                            break
            return {"records": rows, "cursor": cursor}

    def verify(self) -> dict[str, Any]:
        with self._thread_lock, _interprocess_lock(self._lock_path):
            rows, corrupt = self._rows_unlocked()
        return self._integrity_unlocked(rows, corrupt)

    def rewrite_excluding(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        expected_last_hash: str | None,
    ) -> dict[str, Any]:
        """Réécrit atomiquement une chaîne valide en excluant des preuves sélectionnées."""
        with self._thread_lock, _interprocess_lock(self._lock_path):
            self._repair_partial_tail_unlocked()
            rows, corrupt = self._rows_unlocked()
            before = self._integrity_unlocked(rows, corrupt)
            if not before["valid"]:
                raise RuntimeError("L'intégrité du registre interdit sa réécriture.")
            if before.get("last_hash") != expected_last_hash:
                raise RuntimeError("Le registre a changé depuis la sauvegarde de rollback.")
            retained = [row for row in rows if not predicate(row)]
            removed = len(rows) - len(retained)
            if removed == 0:
                raise ValueError("Aucune preuve ne correspond au sélecteur exact.")

            rebuilt: list[dict[str, Any]] = []
            previous_hash = None
            for row in retained:
                business = {key: value for key, value in row.items() if key not in _INTEGRITY_FIELDS}
                normalized = self._normalize_record(business)
                enriched = {
                    **normalized,
                    "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
                    "sequence": len(rebuilt) + 1,
                    "previous_hash": previous_hash,
                }
                enriched["record_hash"] = _digest(enriched)
                encoded = (json.dumps(enriched, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
                if len(encoded) > _MAX_RECORD_BYTES:
                    raise ValueError("Une preuve reconstruite dépasse 2 Mio.")
                rebuilt.append(enriched)
                previous_hash = enriched["record_hash"]
            after = self._integrity_unlocked(rebuilt, 0)
            if not after["valid"]:
                raise RuntimeError("La chaîne reconstruite est invalide.")

            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.rewrite")
            rollback = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.previous")
            try:
                with temporary.open("xb") as stream:
                    for row in rebuilt:
                        stream.write((json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
                if self.path.exists():
                    with self.path.open("rb") as reader, rollback.open("xb") as writer:
                        shutil.copyfileobj(reader, writer, length=1024 * 1024)
                        writer.flush()
                        os.fsync(writer.fileno())
                os.replace(temporary, self.path)
                verified_rows, verified_corrupt = self._rows_unlocked()
                verified = self._integrity_unlocked(verified_rows, verified_corrupt)
                if not verified["valid"] or verified.get("last_hash") != after.get("last_hash"):
                    raise RuntimeError("La validation post-réécriture a échoué.")
            except BaseException:
                if rollback.exists():
                    os.replace(rollback, self.path)
                raise
            finally:
                temporary.unlink(missing_ok=True)
                rollback.unlink(missing_ok=True)
            return {
                "success": True,
                "removed": removed,
                "retained": len(rebuilt),
                "before_last_hash": before.get("last_hash"),
                "after_last_hash": after.get("last_hash"),
            }

    def restore_snapshot(self, snapshot: Path) -> dict[str, Any]:
        """Restaure atomiquement un snapshot JSONL après validation complète de sa chaîne."""
        source = Path(snapshot).resolve()
        if not source.is_file() or source.is_symlink():
            raise ValueError("Snapshot de preuves invalide.")
        candidate = DurableEvidenceStore(
            source,
            stream_name=self.stream_name,
            record_validator=self._record_validator,
        )
        try:
            report = candidate.verify()
        finally:
            candidate._lock_path.unlink(missing_ok=True)
        if not report["valid"]:
            raise RuntimeError("Le snapshot de preuves est invalide.")
        with self._thread_lock, _interprocess_lock(self._lock_path):
            temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.restore")
            try:
                with source.open("rb") as reader, temporary.open("xb") as writer:
                    for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                        writer.write(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            restored_rows, restored_corrupt = self._rows_unlocked()
            restored = self._integrity_unlocked(restored_rows, restored_corrupt)
            if not restored["valid"] or restored.get("last_hash") != report.get("last_hash"):
                raise RuntimeError("La restauration du snapshot a échoué.")
            return restored
