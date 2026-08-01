"""Validation bornee des pieces jointes sortantes."""
from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Any

from storage_layout import roots
from platform_paths import PATHS

MAX_FILES = 10
MAX_TOTAL_BYTES = 18 * 1024 * 1024
ALLOWED_SUFFIXES = {".pdf", ".docx", ".md", ".txt", ".json", ".csv", ".xlsx", ".pptx", ".png", ".jpg", ".jpeg", ".zip"}


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_attachments(raw: Any) -> list[dict[str, Any]]:
    if raw in (None, "", []):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_FILES:
        raise ValueError(f"Les pieces jointes doivent former une liste de {MAX_FILES} fichiers maximum.")
    _, export_root = roots()
    allowed_roots = [
        export_root.resolve(),
        *(Path(PATHS[name]).resolve() for name in ("desktop", "documents", "downloads")),
    ]
    result, total = [], 0
    for item in raw:
        original = item.get("path") if isinstance(item, dict) else item
        path = Path(str(original or "")).expanduser().resolve(strict=True)
        if not any(_inside(path, root) for root in allowed_roots):
            raise ValueError("Une piece jointe doit provenir des exports Marvin, du Bureau, de Documents ou de Telechargements.")
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise ValueError(f"Piece jointe invalide ou interdite : {path.name}")
        content = path.read_bytes()
        total += len(content)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Les pieces jointes depassent la limite brute de 18 Mio.")
        digest = hashlib.sha256(content).hexdigest()
        expected = item.get("sha256") if isinstance(item, dict) else None
        if expected and str(expected).lower() != digest:
            raise ValueError(f"La piece jointe {path.name} a change depuis sa validation.")
        mime, _ = mimetypes.guess_type(path.name)
        result.append({"path": str(path), "name": path.name, "size_bytes": len(content), "sha256": digest, "mime_type": mime or "application/octet-stream"})
    return result
