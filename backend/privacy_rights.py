"""Export sélectif, chiffré et vérifié des registres de preuves Marvin."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from durable_evidence_store import DurableEvidenceStore
from portable_backup_encryption import decrypt_file, encrypt_file


EXPORT_EXTENSION = ".mrvprivacy"
MAX_EXPORT_RECORDS = 100_000
MAX_SELECTOR_CHARS = 1_000


class PrivacyRightsError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportTarget:
    stream_id: str
    selectors: tuple[str, ...]
    store_factory: Callable[[], DurableEvidenceStore]


def _targets() -> dict[str, ExportTarget]:
    import forge
    import frontier_arena
    import mission_os
    import model_market
    import research_swarm
    import truth_ledger

    return {
        "mission_os": ExportTarget("mission_os", ("mission_id", "payload.conversation_id", "payload.action_id"), mission_os._event_store),
        "forge": ExportTarget("forge", ("id", "scenario_id"), forge._runs_store),
        "arena_submissions": ExportTarget("arena_submissions", ("id", "scenario_id"), lambda: frontier_arena._store(frontier_arena.SUBMISSIONS_PATH)),
        "arena_matches": ExportTarget("arena_matches", ("id", "scenario_id"), lambda: frontier_arena._store(frontier_arena.MATCHES_PATH)),
        "arena_votes": ExportTarget("arena_votes", ("id", "match_id"), lambda: frontier_arena._store(frontier_arena.VOTES_PATH)),
        "model_market": ExportTarget("model_market", ("model",), model_market._observation_store),
        "research_swarm": ExportTarget("research_swarm", ("id",), research_swarm._run_store),
        "truth_ledger": ExportTarget("truth_ledger", ("id", "conversation_id", "claims[].id"), truth_ledger._store),
    }


def _path_values(value: Any, selector: str) -> list[Any]:
    current = [value]
    for raw in selector.split("."):
        many = raw.endswith("[]")
        key = raw[:-2] if many else raw
        following: list[Any] = []
        for item in current:
            if not isinstance(item, dict) or key not in item:
                continue
            candidate = item[key]
            if many:
                if isinstance(candidate, list):
                    following.extend(candidate)
            else:
                following.append(candidate)
        current = following
    return current


def _exact_match(record: dict[str, Any], selector: str, expected: str) -> bool:
    return any(str(value) == expected for value in _path_values(record, selector))


def _validate_destination(destination: Path) -> Path:
    target = destination.absolute()
    if target.suffix.lower() != EXPORT_EXTENSION:
        raise PrivacyRightsError(f"La destination doit utiliser {EXPORT_EXTENSION}.")
    if target.exists() or target.is_symlink():
        raise PrivacyRightsError("La destination existe déjà ou est un lien symbolique.")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise PrivacyRightsError("Le dossier de destination doit exister sans lien symbolique.")
    return target


def _default_event_logger(event: str, attributes: dict[str, Any]) -> None:
    try:
        import audit

        audit.log_action(
            event,
            result={
                "success": bool(attributes.get("success")),
                "stream_id": attributes.get("stream_id"),
                "selector": attributes.get("selector"),
                "records": int(attributes.get("records") or 0),
                "error": attributes.get("error_code"),
            },
            source="offline_privacy_export",
        )
    except Exception:
        pass


def create_export(
    stream_id: str,
    selector: str,
    selector_value: str,
    destination: Path,
    *,
    passphrase: str,
    event_logger: Callable[[str, dict[str, Any]], None] = _default_event_logger,
    targets: dict[str, ExportTarget] | None = None,
) -> dict[str, Any]:
    catalog = targets if targets is not None else _targets()
    target = catalog.get(str(stream_id).strip())
    if target is None:
        raise PrivacyRightsError("Registre d'export inconnu.")
    selected_field = str(selector).strip()
    if selected_field not in target.selectors:
        raise PrivacyRightsError("Sélecteur non autorisé pour ce registre.")
    expected = str(selector_value)
    if not 1 <= len(expected) <= MAX_SELECTOR_CHARS:
        raise PrivacyRightsError("Valeur de sélection invalide.")
    output = _validate_destination(destination)
    store = target.store_factory()
    integrity = store.verify()
    if not integrity.get("valid"):
        raise PrivacyRightsError("L'intégrité du registre source est invalide.")
    record_count = int(integrity.get("records") or 0)
    if record_count > MAX_EXPORT_RECORDS:
        raise PrivacyRightsError("Le registre dépasse la limite d'export sélectif.")
    rows = list(reversed(store.recent_verified(record_count or 1))) if record_count else []
    selected = [row for row in rows if _exact_match(row, selected_field, expected)]
    if not selected:
        raise PrivacyRightsError("Aucun enregistrement ne correspond au sélecteur exact.")

    plain = output.parent / f".privacy-export.{uuid.uuid4().hex}.json"
    encrypted = output.parent / f".{output.name}.{uuid.uuid4().hex}.partial"
    verify_plain = output.parent / f".privacy-verify.{uuid.uuid4().hex}.json"
    payload = {
        "schema_version": 1,
        "kind": "marvin_privacy_export",
        "stream_id": target.stream_id,
        "selector": selected_field,
        "selector_value": expected,
        "source_integrity": {
            "records": record_count,
            "last_hash": integrity.get("last_hash"),
            "integrity_level": integrity.get("integrity_level"),
        },
        "records": selected,
    }
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        plain.write_bytes(encoded)
        encryption = encrypt_file(plain, encrypted, passphrase=passphrase)
        verification = decrypt_file(encrypted, verify_plain, passphrase=passphrase)
        if verify_plain.read_bytes() != encoded or verification["sha256"] != hashlib.sha256(encoded).hexdigest():
            raise PrivacyRightsError("La vérification de l'export chiffré a échoué.")
        os.replace(encrypted, output)
        result = {
            "success": True,
            "filename": output.name,
            "size_bytes": output.stat().st_size,
            "records": len(selected),
            "stream_id": target.stream_id,
            "selector": selected_field,
            "encrypted": True,
            "integrity_verified": True,
            "plaintext_sha256": encryption["sha256"],
        }
        event_logger("privacy_export_create", result)
        return result
    except Exception as exc:
        event_logger("privacy_export_create", {"success": False, "stream_id": target.stream_id, "selector": selected_field, "error_code": type(exc).__name__})
        raise
    finally:
        plain.unlink(missing_ok=True)
        encrypted.unlink(missing_ok=True)
        verify_plain.unlink(missing_ok=True)


def erase_exact(
    stream_id: str,
    selector: str,
    selector_value: str,
    rollback_destination: Path,
    *,
    passphrase: str,
    confirmed: bool,
    event_logger: Callable[[str, dict[str, Any]], None] = _default_event_logger,
    targets: dict[str, ExportTarget] | None = None,
) -> dict[str, Any]:
    if confirmed is not True:
        raise PrivacyRightsError("Une confirmation explicite est requise.")
    catalog = targets if targets is not None else _targets()
    target = catalog.get(str(stream_id).strip())
    if target is None:
        raise PrivacyRightsError("Registre d'effacement inconnu.")
    selected_field = str(selector).strip()
    if selected_field not in target.selectors:
        raise PrivacyRightsError("Sélecteur non autorisé pour ce registre.")
    expected = str(selector_value)
    if not 1 <= len(expected) <= MAX_SELECTOR_CHARS:
        raise PrivacyRightsError("Valeur de sélection invalide.")
    rollback = _validate_destination(rollback_destination)
    store = target.store_factory()
    before = store.verify()
    if not before.get("valid") or not store.path.is_file():
        raise PrivacyRightsError("L'intégrité du registre source est invalide.")
    count = int(before.get("records") or 0)
    if count > MAX_EXPORT_RECORDS:
        raise PrivacyRightsError("Le registre dépasse la limite de réécriture.")
    rows = list(reversed(store.recent_verified(count or 1))) if count else []
    matches = sum(_exact_match(row, selected_field, expected) for row in rows)
    if matches == 0:
        raise PrivacyRightsError("Aucune preuve ne correspond au sélecteur exact.")

    encrypted = rollback.parent / f".{rollback.name}.{uuid.uuid4().hex}.partial"
    verify_plain = rollback.parent / f".privacy-rollback-verify.{uuid.uuid4().hex}.jsonl"
    try:
        encryption = encrypt_file(store.path, encrypted, passphrase=passphrase)
        decrypt_file(encrypted, verify_plain, passphrase=passphrase)
        if verify_plain.read_bytes() != store.path.read_bytes():
            raise PrivacyRightsError("La sauvegarde de rollback ne correspond pas à la source.")
        os.replace(encrypted, rollback)
        rewrite = store.rewrite_excluding(
            lambda row: _exact_match(row, selected_field, expected),
            expected_last_hash=before.get("last_hash"),
        )
        remaining = store.recent_verified(int(rewrite["retained"]) or 1) if rewrite["retained"] else []
        if any(_exact_match(row, selected_field, expected) for row in remaining):
            raise PrivacyRightsError("Le sélecteur reste présent après réécriture.")
        result = {
            "success": True,
            "operation_id": uuid.uuid4().hex,
            "stream_id": target.stream_id,
            "selector": selected_field,
            "removed": rewrite["removed"],
            "retained": rewrite["retained"],
            "before_last_hash": rewrite["before_last_hash"],
            "after_last_hash": rewrite["after_last_hash"],
            "rollback_filename": rollback.name,
            "rollback_sha256": hashlib.sha256(rollback.read_bytes()).hexdigest(),
            "source_plaintext_sha256": encryption["sha256"],
            "rollback_contains_erased_data": True,
            "finalization_required": True,
        }
        event_logger("privacy_erasure_rechain", result)
        return result
    except Exception as exc:
        event_logger("privacy_erasure_rechain", {"success": False, "stream_id": target.stream_id, "selector": selected_field, "error_code": type(exc).__name__})
        raise
    finally:
        encrypted.unlink(missing_ok=True)
        verify_plain.unlink(missing_ok=True)


def restore_rollback(
    stream_id: str,
    rollback_source: Path,
    *,
    passphrase: str,
    confirmed: bool,
    targets: dict[str, ExportTarget] | None = None,
) -> dict[str, Any]:
    if confirmed is not True:
        raise PrivacyRightsError("Une confirmation explicite est requise.")
    catalog = targets if targets is not None else _targets()
    target = catalog.get(str(stream_id).strip())
    if target is None:
        raise PrivacyRightsError("Registre de restauration inconnu.")
    source = rollback_source.absolute()
    if source.suffix.lower() != EXPORT_EXTENSION or not source.is_file() or source.is_symlink():
        raise PrivacyRightsError("Bundle de rollback invalide.")
    store = target.store_factory()
    plain = source.parent / f".privacy-rollback-restore.{uuid.uuid4().hex}.jsonl"
    try:
        decrypt_file(source, plain, passphrase=passphrase)
        report = store.restore_snapshot(plain)
        return {
            "success": True,
            "stream_id": target.stream_id,
            "records": report["records"],
            "last_hash": report["last_hash"],
            "integrity_verified": True,
        }
    finally:
        plain.unlink(missing_ok=True)
