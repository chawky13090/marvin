"""Création de mini-applications HTML autonomes, bornées et atomiques."""

from __future__ import annotations

import asyncio
import hashlib
import html
import os
import re
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any


_output_root: Path | None = None
_token_factory: Callable[[], str] = lambda: uuid.uuid4().hex[:8]

_MAX_HTML_BYTES = 2 * 1024 * 1024
_CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src data: blob:; "
    "media-src data: blob:; "
    "font-src data:; "
    "connect-src 'none'; "
    "object-src 'none'; "
    "frame-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)
_CSP_META = (
    '<meta http-equiv="Content-Security-Policy" '
    f'content="{_CSP}">'
)


def configure(
    *,
    output_root: str | Path,
    token_factory: Callable[[], str] | None = None,
) -> None:
    global _output_root, _token_factory
    _output_root = Path(output_root).resolve()
    _token_factory = token_factory or (lambda: uuid.uuid4().hex[:8])


def _safe_title(value: Any) -> tuple[str, str]:
    title = str(value or "webapp").strip()[:120] or "webapp"
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", title)[:60].strip("_") or "webapp"
    return title, slug


def _with_document_shell(content: str, title: str) -> str:
    if "<html" not in content.lower():
        return (
            '<!DOCTYPE html>\n<html lang="fr"><head><meta charset="utf-8">'
            f"{_CSP_META}<title>{html.escape(title)}</title></head>"
            f"<body>\n{content}\n</body></html>"
        )
    csp_meta = re.compile(
        r"<meta\b(?=[^>]*http-equiv\s*=\s*['\"]?content-security-policy)[^>]*>",
        re.I,
    )
    if csp_meta.search(content):
        return csp_meta.sub(_CSP_META, content)
    head = re.search(r"<head\b[^>]*>", content, re.I)
    if head:
        return content[: head.end()] + _CSP_META + content[head.end() :]
    html_tag = re.search(r"<html\b[^>]*>", content, re.I)
    if html_tag:
        return content[: html_tag.end()] + f"<head>{_CSP_META}</head>" + content[html_tag.end() :]
    return _CSP_META + content


def _write_atomic(directory: Path, content: str) -> Path:
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / "index.html"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=".index-",
            suffix=".tmp",
            dir=directory,
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, target)
        return target
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        try:
            directory.rmdir()
        except OSError:
            pass
        raise


async def create(args: dict[str, Any]) -> dict[str, Any]:
    if _output_root is None:
        raise RuntimeError("Le domaine Webapp n'est pas configuré.")
    raw_content = args.get("content")
    if not isinstance(raw_content, str) or not raw_content.strip():
        return {"error": "Paramètre 'content' requis (code HTML complet)."}
    if "\x00" in raw_content:
        return {"error": "Le contenu HTML contient un caractère nul interdit."}
    title, slug = _safe_title(args.get("title"))
    content = _with_document_shell(raw_content.strip(), title)
    encoded = content.encode("utf-8")
    if len(encoded) > _MAX_HTML_BYTES:
        return {
            "error": "Le contenu HTML dépasse la limite de 2 Mio.",
            "max_bytes": _MAX_HTML_BYTES,
        }
    token = re.sub(r"[^a-zA-Z0-9_-]", "", str(_token_factory()))[:24] or "generated"
    directory = (_output_root / f"{slug}_{token}").resolve()
    if directory.parent != _output_root:
        return {"error": "Chemin de sortie Webapp invalide."}
    try:
        path = await asyncio.to_thread(_write_atomic, directory, content)
    except FileExistsError:
        return {"error": "Collision de nom Webapp; veuillez réessayer."}
    except OSError as exc:
        return {
            "error": "Impossible d'enregistrer la mini-application.",
            "error_type": type(exc).__name__,
        }
    return {
        "success": True,
        "path": str(path),
        "title": title,
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "network_policy": "offline",
        "message": f"Mini-appli « {title} » créée; clique pour l'ouvrir.",
    }
