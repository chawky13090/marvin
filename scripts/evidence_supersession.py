"""Validation fermee du registre externe de supersession des preuves."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ALLOWED_STATES = {"current", "superseded", "invalidated", "historical_only"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repository_path(root: Path, raw: str) -> Path:
    value = Path(raw)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError(f"Chemin de preuve non relatif ou traversant : {raw}")
    resolved = (root / value).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Chemin de preuve hors depot : {raw}") from exc
    if not resolved.is_file():
        raise ValueError(f"Artefact de preuve absent : {raw}")
    return resolved


def _validate_selector(document: Any, selector: dict[str, str], subject: str) -> None:
    collection = selector.get("collection")
    key = selector.get("key")
    value = selector.get("value")
    if not collection or not key or not value:
        raise ValueError(f"Selecteur incomplet pour {subject}")
    rows = document.get(collection) if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"Collection {collection} absente pour {subject}")
    matches = [row for row in rows if isinstance(row, dict) and row.get(key) == value]
    if len(matches) != 1:
        raise ValueError(f"Selecteur non unique pour {subject}: {len(matches)} correspondances")


def validate_registry(registry: dict[str, Any], *, root: Path) -> dict[str, dict[str, Any]]:
    if registry.get("schema") != "marvin.evidence-supersession-registry/1.0":
        raise ValueError("Schema de registre de supersession non supporte")
    preregistration = registry.get("preregistration")
    if not isinstance(preregistration, dict):
        raise ValueError("Pre-enregistrement absent du registre")
    policy_path = _repository_path(root, str(preregistration.get("path") or ""))
    if sha256(policy_path) != preregistration.get("sha256"):
        raise ValueError("Empreinte du pre-enregistrement divergente")
    if not isinstance(registry.get("preregistration_commit"), str):
        raise ValueError("Commit du pre-enregistrement absent")
    subjects = registry.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        raise ValueError("Le registre ne contient aucun sujet")
    seen_subjects: set[str] = set()
    terminals: dict[str, dict[str, Any]] = {}
    for entry in subjects:
        subject = entry.get("subject")
        if not isinstance(subject, str) or not subject or subject in seen_subjects:
            raise ValueError(f"Sujet absent ou duplique : {subject!r}")
        seen_subjects.add(subject)
        revisions = entry.get("revisions")
        if not isinstance(revisions, list) or not revisions:
            raise ValueError(f"Aucune revision pour {subject}")
        by_id: dict[str, dict[str, Any]] = {}
        incoming: dict[str, int] = {}
        for revision in revisions:
            revision_id = revision.get("id")
            state = revision.get("state")
            if not isinstance(revision_id, str) or revision_id in by_id:
                raise ValueError(f"Revision absente ou dupliquee pour {subject}")
            if state not in ALLOWED_STATES:
                raise ValueError(f"Etat invalide {state!r} pour {subject}")
            artifact = revision.get("artifact")
            if not isinstance(artifact, dict):
                raise ValueError(f"Artefact absent pour {subject}/{revision_id}")
            path = _repository_path(root, str(artifact.get("path") or ""))
            expected = artifact.get("sha256")
            if not isinstance(expected, str) or sha256(path) != expected:
                raise ValueError(f"Empreinte divergente pour {subject}/{revision_id}")
            selector = artifact.get("selector")
            if selector is not None:
                try:
                    document = json.loads(path.read_text(encoding="utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"Artefact selectif illisible pour {subject}") from exc
                if not isinstance(selector, dict):
                    raise ValueError(f"Selecteur invalide pour {subject}")
                _validate_selector(document, selector, subject)
            by_id[revision_id] = revision
            incoming[revision_id] = 0
        current = [revision for revision in revisions if revision["state"] == "current"]
        if len(current) != 1:
            raise ValueError(f"Le sujet {subject} doit avoir exactement une revision courante")
        for revision in revisions:
            successor = revision.get("successor")
            if revision["state"] != "current":
                if successor not in by_id:
                    raise ValueError(f"Successeur absent pour {subject}/{revision['id']}")
                incoming[successor] += 1
                if incoming[successor] > 1:
                    raise ValueError(f"Successeurs concurrents vers {subject}/{successor}")
            elif successor is not None:
                raise ValueError(f"Seule une revision supersedee peut avoir un successeur : {subject}")
        terminal_id = current[0]["id"]
        for revision in revisions:
            visited: set[str] = set()
            cursor = revision["id"]
            while by_id[cursor]["state"] != "current":
                if cursor in visited:
                    raise ValueError(f"Cycle de supersession pour {subject}")
                visited.add(cursor)
                cursor = by_id[cursor]["successor"]
            if cursor != terminal_id:
                raise ValueError(f"Chaine non terminale vers la revision courante pour {subject}")
        terminals[subject] = current[0]
    return terminals


def load_and_validate(path: Path, *, root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    return registry, validate_registry(registry, root=root)
