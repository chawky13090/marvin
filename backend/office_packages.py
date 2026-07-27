"""Validation bornée des conteneurs ZIP Open XML (DOCX, PPTX, XLSX)."""

from __future__ import annotations

import zipfile
from pathlib import Path


MAX_OFFICE_FILE_BYTES = 100 * 1024 * 1024
MAX_OFFICE_MEMBERS = 10_000
MAX_OFFICE_EXPANDED_BYTES = 500 * 1024 * 1024
MAX_OFFICE_COMPRESSION_RATIO = 1_000


def validate_office_package(path: Path, *, suffix: str, marker: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    if path.suffix.casefold() != suffix:
        raise ValueError(f"Extension attendue : {suffix}.")
    size = path.stat().st_size
    if size > MAX_OFFICE_FILE_BYTES:
        raise ValueError("Document Office limité à 100 Mio.")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = archive.infolist()
            if len(members) > MAX_OFFICE_MEMBERS:
                raise ValueError(
                    f"Document Office limité à {MAX_OFFICE_MEMBERS} composants."
                )
            names = {item.filename for item in members}
            if marker not in names:
                raise ValueError("Structure Open XML attendue absente.")
            expanded = sum(item.file_size for item in members)
            compressed = sum(item.compress_size for item in members)
            if expanded > MAX_OFFICE_EXPANDED_BYTES:
                raise ValueError("Document Office décompressé limité à 500 Mio.")
            if (
                compressed > 0
                and expanded / compressed > MAX_OFFICE_COMPRESSION_RATIO
            ):
                raise ValueError("Taux de compression Office anormal.")
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ValueError(f"Composant Office corrompu : {bad_member}")
    except zipfile.BadZipFile as exc:
        raise ValueError("Conteneur Open XML invalide.") from exc
