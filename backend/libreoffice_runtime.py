"""Détection et rendu LibreOffice isolé pour la validation documentaire."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


def find_soffice() -> Path | None:
    candidates = [
        shutil.which("soffice.com") or shutil.which("soffice"),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "LibreOffice/program/soffice.com",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "LibreOffice/program/soffice.com",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/LibreOffice/program/soffice.com",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    return None


def capability() -> dict[str, Any]:
    executable = find_soffice()
    if executable is None:
        return {"status": "unavailable", "available": False, "detail": "LibreOffice absent.", "executable": None}
    try:
        completed = subprocess.run(
            [str(executable), "--headless", "--version"],
            capture_output=True, text=True, errors="replace", timeout=10, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        version = (completed.stdout or completed.stderr or "").strip().splitlines()[0]
        if completed.returncode == 0:
            return {"status": "available", "available": True, "detail": version, "version": version, "executable": str(executable)}
        return {"status": "degraded", "available": False, "detail": "LibreOffice détecté mais non exécutable.", "executable": str(executable)}
    except Exception as exc:
        return {"status": "degraded", "available": False, "detail": f"LibreOffice en erreur : {type(exc).__name__}", "executable": str(executable)}


def render_docx_to_pdf(source: str | Path, output_dir: str | Path, *, timeout: int = 90) -> dict[str, Any]:
    source_path = Path(source).resolve()
    destination = Path(output_dir).resolve()
    executable = find_soffice()
    if not source_path.is_file() or source_path.suffix.casefold() != ".docx":
        return {"success": False, "error": "Un DOCX existant est requis."}
    if executable is None:
        return {"success": False, "status": "unavailable", "error": "LibreOffice absent."}
    destination.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="marvin-lo-profile-") as profile:
        profile_uri = Path(profile).resolve().as_uri()
        command = [
            str(executable), "--headless", "--nologo", "--nodefault", "--nolockcheck",
            f"-env:UserInstallation={profile_uri}", "--convert-to", "pdf:writer_pdf_Export",
            "--outdir", str(destination), str(source_path),
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, errors="replace", timeout=max(10, min(timeout, 180)),
                check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return {"success": False, "status": "timeout", "error": "Conversion LibreOffice expirée.", "duration_ms": int((time.monotonic() - started) * 1000)}
    pdf_path = destination / f"{source_path.stem}.pdf"
    success = completed.returncode == 0 and pdf_path.is_file() and pdf_path.stat().st_size > 0
    return {
        "success": success,
        "status": "verified" if success else "failed",
        "path": str(pdf_path) if success else None,
        "size_bytes": pdf_path.stat().st_size if success else 0,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "error": None if success else ((completed.stderr or completed.stdout or "Conversion échouée.")[-500:]),
    }


def validate_docx_render(source: str | Path, *, timeout: int = 90) -> dict[str, Any]:
    """Convertit puis contrôle chaque page sans conserver de copie intermédiaire."""
    with tempfile.TemporaryDirectory(prefix="marvin-docx-qa-") as output:
        rendered = render_docx_to_pdf(source, output, timeout=timeout)
        if not rendered.get("success"):
            status = "degraded" if rendered.get("status") == "unavailable" else "failed"
            return {**rendered, "status": status}
        try:
            import fitz
            pdf = fitz.open(rendered["path"])
            pages = []
            for index, page in enumerate(pdf):
                text = page.get_text("text").strip()
                pixmap = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5), alpha=False)
                pages.append({
                    "page": index + 1,
                    "width": pixmap.width,
                    "height": pixmap.height,
                    "text_characters": len(text),
                    "nonempty": bool(text or page.get_images(full=True)),
                })
            pdf.close()
            valid = bool(pages) and all(item["nonempty"] for item in pages)
            return {
                "success": valid,
                "status": "verified" if valid else "failed",
                "engine": "libreoffice",
                "page_count": len(pages),
                "pages": pages,
                "duration_ms": rendered.get("duration_ms", 0),
                "error": None if valid else "Une ou plusieurs pages rendues sont vides.",
            }
        except Exception as exc:
            return {"success": False, "status": "failed", "engine": "libreoffice", "error": f"Inspection PDF impossible : {type(exc).__name__}"}
