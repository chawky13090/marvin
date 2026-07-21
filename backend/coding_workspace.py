"""Git worktree isolation and durable metadata for autonomous coding missions."""
from __future__ import annotations

import json
import os
import re
import subprocess
import shutil
import threading
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR
import repository_intelligence
import deliverable_bundle


ROOT = Path(DATA_DIR) / "coding_workspaces"
_LOCK = threading.RLock()
_MISSION_ID = re.compile(r"^[0-9a-f]{32}$")


class WorkspaceError(RuntimeError):
    """Raised when worktree isolation cannot be guaranteed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _directory(mission_id: str) -> Path:
    if not _MISSION_ID.fullmatch(mission_id):
        raise WorkspaceError("Identifiant de mission invalide.")
    return ROOT / mission_id


def _run(root: Path, *args: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkspaceError(f"Git indisponible ou trop lent : {exc}") from exc
    if result.returncode:
        raise WorkspaceError((result.stderr or result.stdout).strip()[:1_000] or "Git a refusé l'opération.")
    return result.stdout.strip()


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def get(mission_id: str) -> dict[str, Any] | None:
    path = _directory(mission_id) / "workspace.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def create(mission_id: str, repository_path: str, *, confirmed: bool, base_ref: str = "HEAD") -> dict[str, Any]:
    """Create one isolated branch/worktree. This never modifies tracked files in the source checkout."""
    if not confirmed:
        raise WorkspaceError("La création du worktree doit être confirmée explicitement.")
    contract = repository_intelligence.inspect(repository_path)
    source = Path(contract["root"])
    if not contract["git"].get("available"):
        raise WorkspaceError("L'autonomie isolée exige un dépôt Git initialisé.")
    if base_ref not in {"HEAD", "origin/HEAD"}:
        raise WorkspaceError("Référence de départ non autorisée.")

    with _LOCK:
        existing = get(mission_id)
        if existing:
            return status(mission_id)
        directory = _directory(mission_id)
        worktree = directory / "repo"
        branch = f"marvin/mission-{mission_id[:12]}"
        directory.mkdir(parents=True, exist_ok=False)
        try:
            reference = base_ref
            if base_ref == "origin/HEAD":
                try:
                    _run(source, "rev-parse", "--verify", "origin/HEAD")
                except WorkspaceError:
                    reference = "HEAD"
            _run(source, "worktree", "add", "--detach", str(worktree), reference, timeout=120)
            _run(worktree, "switch", "-c", branch)
            metadata = {
                "mission_id": mission_id,
                "source_root": str(source),
                "worktree_root": str(worktree),
                "branch": branch,
                "base_ref": reference,
                "base_commit": _run(worktree, "rev-parse", "HEAD"),
                "contract_hash": contract["contract_hash"],
                "source_was_dirty": bool(contract["git"].get("dirty")),
                "created_at": _now(),
            }
            _atomic_write(directory / "workspace.json", metadata)
            return status(mission_id)
        except Exception:
            try:
                if worktree.exists():
                    _run(source, "worktree", "remove", "--force", str(worktree), timeout=120)
            except WorkspaceError:
                pass
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)
            raise


def status(mission_id: str) -> dict[str, Any]:
    metadata = get(mission_id)
    if not metadata:
        raise WorkspaceError("Worktree de mission introuvable.")
    worktree = Path(metadata["worktree_root"])
    if not worktree.is_dir():
        return {**metadata, "available": False, "dirty": False, "changed_count": 0, "changes": []}
    porcelain = _run(worktree, "status", "--porcelain=v1", "--untracked-files=normal")
    changes = porcelain.splitlines() if porcelain else []
    return {
        **metadata,
        "available": True,
        "head": _run(worktree, "rev-parse", "HEAD"),
        "dirty": bool(changes),
        "changed_count": len(changes),
        "changes": changes[:500],
        "ahead": int(_run(worktree, "rev-list", "--count", f"{metadata['base_commit']}..HEAD") or 0),
    }


def diff(mission_id: str, *, max_chars: int = 200_000) -> dict[str, Any]:
    metadata = get(mission_id)
    if not metadata:
        raise WorkspaceError("Worktree de mission introuvable.")
    worktree = Path(metadata["worktree_root"])
    if not worktree.is_dir():
        raise WorkspaceError("Le dossier du worktree n'existe plus.")
    patch = _run(worktree, "diff", "--no-ext-diff", "--binary", metadata["base_commit"], "--", timeout=60)
    encoded = patch.encode("utf-8")
    truncated = len(encoded) > max_chars
    if truncated:
        patch = encoded[:max_chars].decode("utf-8", errors="replace")
    return {"patch": patch, "truncated": truncated, "bytes": len(encoded)}


def apply_files(mission_id: str, files: dict[str, str], *, max_files_changed: int) -> dict[str, Any]:
    """Atomically materialize an accepted bundle inside the isolated worktree only."""
    metadata = get(mission_id)
    if not metadata:
        raise WorkspaceError("Worktree de mission introuvable.")
    worktree = Path(metadata["worktree_root"]).resolve(strict=True)
    if len(files) > max_files_changed:
        raise WorkspaceError("Le livrable dépasse le budget de fichiers de la mission.")
    before = status(mission_id)
    if before["changed_count"] > max_files_changed:
        raise WorkspaceError("Le worktree dépasse déjà le budget de fichiers; intervention requise.")

    normalized: dict[str, str] = {}
    for raw_path, content in files.items():
        try:
            relative = deliverable_bundle.normalize_path(raw_path)
        except deliverable_bundle.BundleError as exc:
            raise WorkspaceError(str(exc)) from exc
        parts = Path(relative).parts
        if not parts or parts[0].casefold() == ".git":
            raise WorkspaceError("Écriture dans les métadonnées Git interdite.")
        normalized[relative] = str(content)

    backups: dict[Path, bytes | None] = {}
    temporary_paths: list[Path] = []
    try:
        for relative, content in normalized.items():
            destination = (worktree / Path(relative)).resolve(strict=False)
            try:
                destination.relative_to(worktree)
            except ValueError as exc:
                raise WorkspaceError("Le fichier généré sort du worktree.") from exc
            parent = destination.parent
            cursor = worktree
            for part in destination.relative_to(worktree).parts[:-1]:
                cursor /= part
                if cursor.exists() and cursor.is_symlink():
                    raise WorkspaceError("Écriture via un lien symbolique interdite.")
            backups[destination] = destination.read_bytes() if destination.exists() else None
            parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".marvin-tmp")
            temporary.write_text(content, encoding="utf-8", newline="\n")
            temporary_paths.append(temporary)
            os.replace(temporary, destination)
        after = status(mission_id)
        if after["changed_count"] > max_files_changed:
            raise WorkspaceError("Les changements dépassent le budget de fichiers de la mission.")
    except Exception:
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)
        for destination, previous in backups.items():
            if previous is None:
                destination.unlink(missing_ok=True)
            else:
                destination.write_bytes(previous)
        raise

    manifest = [
        {"path": path, "bytes": len(content.encode("utf-8")),
         "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
        for path, content in sorted(normalized.items())
    ]
    return {"applied": True, "manifest": manifest, "workspace": status(mission_id)}
